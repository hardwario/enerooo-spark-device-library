package tui

import (
	"fmt"
	"strings"

	"github.com/charmbracelet/bubbles/spinner"
	"github.com/charmbracelet/bubbles/textarea"
	"github.com/charmbracelet/bubbles/textinput"
	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
	"gopkg.in/yaml.v3"

	"github.com/hardwario/enerooo-spark-device-library/tools/sparkctl/internal/github"
	"github.com/hardwario/enerooo-spark-device-library/tools/sparkctl/internal/models"
	"github.com/hardwario/enerooo-spark-device-library/tools/sparkctl/internal/source"
	"github.com/hardwario/enerooo-spark-device-library/tools/sparkctl/internal/state"
)

// Messages
type (
	manifestLoadedMsg struct{ manifest *models.Manifest }
	deviceFileLoadedMsg struct {
		path string
		file *models.DeviceFile
		sha  string
	}
	errorMsg       struct{ err error }
	prCreatedMsg   struct{ url string }
	filesSavedMsg  struct{ count int }
	statusMsg      struct{ msg string }
)

// DataSource interface for fetching data
type DataSource interface {
	FetchManifest() (*models.Manifest, error)
	FetchDeviceFile(path string) (*models.DeviceFile, string, error)
	CanWrite() bool
}

// Model is the main TUI model
type Model struct {
	state      *state.State
	source     DataSource
	ghClient   *github.Client      // For PR creation (nil in local mode)
	local      *source.LocalSource // For local saves (nil in GitHub mode)
	localMode  bool
	spinner    spinner.Model
	input      textinput.Model
	textarea   textarea.Model
	width      int
	height     int
	status     string
	editingCfg string // which config is being edited: "control", "technology", "processor"
}

// NewModel creates a new TUI model
func NewModel(localMode bool, localPath string) Model {
	s := spinner.New()
	s.Spinner = spinner.Dot
	s.Style = lipgloss.NewStyle().Foreground(primaryColor)

	ti := textinput.New()
	ti.Focus()
	ti.CharLimit = 256
	ti.Width = 50

	ta := textarea.New()
	ta.SetWidth(70)
	ta.SetHeight(15)
	ta.ShowLineNumbers = false

	m := Model{
		state:     state.NewState(),
		localMode: localMode,
		spinner:   s,
		input:     ti,
		textarea:  ta,
		width:     80,
		height:    24,
	}

	if localMode {
		localSrc := source.NewLocalSource(localPath)
		m.source = localSrc
		m.local = localSrc
	} else {
		ghClient := github.NewClient()
		m.source = ghClient
		m.ghClient = ghClient
	}

	return m
}

// Init initializes the TUI
func (m Model) Init() tea.Cmd {
	return tea.Batch(
		m.spinner.Tick,
		m.loadManifest,
	)
}

func (m Model) loadManifest() tea.Msg {
	manifest, err := m.source.FetchManifest()
	if err != nil {
		return errorMsg{err}
	}
	return manifestLoadedMsg{manifest}
}

func (m Model) loadDeviceFile(path string) tea.Cmd {
	return func() tea.Msg {
		file, sha, err := m.source.FetchDeviceFile(path)
		if err != nil {
			return errorMsg{err}
		}
		return deviceFileLoadedMsg{path, file, sha}
	}
}

// Update handles messages
func (m Model) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	var cmds []tea.Cmd

	switch msg := msg.(type) {
	case tea.WindowSizeMsg:
		m.width = msg.Width
		m.height = msg.Height

	case tea.KeyMsg:
		// Global keys
		if msg.String() == "ctrl+c" || msg.String() == "q" {
			if m.state.CurrentView == state.ViewVendorList {
				return m, tea.Quit
			}
		}

		// Handle view-specific keys
		cmd := m.handleKeyPress(msg)
		if cmd != nil {
			cmds = append(cmds, cmd)
		}

	case spinner.TickMsg:
		var cmd tea.Cmd
		m.spinner, cmd = m.spinner.Update(msg)
		cmds = append(cmds, cmd)

	case manifestLoadedMsg:
		m.state.Manifest = msg.manifest
		m.state.CurrentView = state.ViewVendorList
		m.status = fmt.Sprintf("Loaded %d vendors", len(msg.manifest.Vendors))

	case deviceFileLoadedMsg:
		// Deep copy for modified version
		modifiedFile := deepCopyDeviceFile(msg.file)
		m.state.Files[msg.path] = &state.FileState{
			Path:     msg.path,
			SHA:      msg.sha,
			Original: msg.file,
			Modified: modifiedFile,
		}
		m.state.CurrentView = state.ViewDeviceList
		m.state.SelectedDeviceIdx = 0
		m.status = fmt.Sprintf("Loaded %d devices", len(msg.file.DeviceTypes))

	case errorMsg:
		m.state.Error = msg.err
		m.state.CurrentView = state.ViewError

	case prCreatedMsg:
		m.status = fmt.Sprintf("PR created: %s", msg.url)
		m.state.CurrentView = state.ViewVendorList
		// Clear changes
		for _, f := range m.state.Files {
			f.HasChanges = false
		}

	case filesSavedMsg:
		m.status = fmt.Sprintf("Saved %d file(s) locally", msg.count)
		m.state.CurrentView = state.ViewVendorList
		// Clear changes
		for _, f := range m.state.Files {
			f.HasChanges = false
		}

	case statusMsg:
		m.status = msg.msg
	}

	// Update text input if editing
	if m.state.IsEditing {
		var cmd tea.Cmd
		m.input, cmd = m.input.Update(msg)
		cmds = append(cmds, cmd)
	}

	// Update textarea if editing config
	if m.state.CurrentView == state.ViewEditConfig {
		var cmd tea.Cmd
		m.textarea, cmd = m.textarea.Update(msg)
		cmds = append(cmds, cmd)
	}

	return m, tea.Batch(cmds...)
}

func (m *Model) handleKeyPress(msg tea.KeyMsg) tea.Cmd {
	key := msg.String()

	// If editing, handle input
	if m.state.IsEditing {
		switch key {
		case "enter":
			m.applyEdit()
			m.state.IsEditing = false
			return nil
		case "esc":
			m.state.IsEditing = false
			return nil
		}
		return nil
	}

	switch m.state.CurrentView {
	case state.ViewVendorList:
		return m.handleVendorListKeys(key)
	case state.ViewDeviceList:
		return m.handleDeviceListKeys(key)
	case state.ViewDeviceDetail:
		return m.handleDeviceDetailKeys(key)
	case state.ViewDeviceEdit:
		return m.handleDeviceEditKeys(key)
	case state.ViewEditConfig:
		return m.handleEditConfigKeys(key)
	case state.ViewConfirmPR:
		return m.handleConfirmSaveKeys(key)
	case state.ViewError:
		if key == "esc" || key == "enter" {
			m.state.CurrentView = state.ViewVendorList
		}
	}

	return nil
}

func (m *Model) handleVendorListKeys(key string) tea.Cmd {
	switch key {
	case "up", "k":
		if m.state.SelectedVendorIdx > 0 {
			m.state.SelectedVendorIdx--
		}
	case "down", "j":
		if m.state.Manifest != nil && m.state.SelectedVendorIdx < len(m.state.Manifest.Vendors)-1 {
			m.state.SelectedVendorIdx++
		}
	case "enter":
		vendor := m.state.CurrentVendor()
		if vendor != nil {
			m.state.CurrentView = state.ViewLoading
			return m.loadDeviceFile("devices/" + vendor.File)
		}
	case "p", "s":
		if m.state.HasPendingChanges() {
			m.state.CurrentView = state.ViewConfirmPR
		}
	}
	return nil
}

func (m *Model) handleDeviceListKeys(key string) tea.Cmd {
	file := m.state.CurrentFile()
	if file == nil || file.Modified == nil {
		return nil
	}

	switch key {
	case "up", "k":
		if m.state.SelectedDeviceIdx > 0 {
			m.state.SelectedDeviceIdx--
		}
	case "down", "j":
		if m.state.SelectedDeviceIdx < len(file.Modified.DeviceTypes)-1 {
			m.state.SelectedDeviceIdx++
		}
	case "enter":
		m.state.CurrentView = state.ViewDeviceDetail
		m.state.SelectedFieldIdx = 0
	case "esc", "backspace":
		m.state.CurrentView = state.ViewVendorList
	case "n":
		// Add new device
		newDevice := models.DeviceType{
			VendorName:       m.state.CurrentVendor().Name,
			Name:             "New Device",
			DeviceType:       "power_meter",
			TechnologyConfig: map[string]interface{}{"technology": "modbus"},
			ControlConfig:    map[string]interface{}{},
			ProcessorConfig:  map[string]interface{}{},
		}
		file.Modified.DeviceTypes = append(file.Modified.DeviceTypes, newDevice)
		m.state.SelectedDeviceIdx = len(file.Modified.DeviceTypes) - 1
		m.state.MarkFileChanged()
		m.state.CurrentView = state.ViewDeviceEdit
	}
	return nil
}

func (m *Model) handleDeviceDetailKeys(key string) tea.Cmd {
	switch key {
	case "esc", "backspace":
		m.state.CurrentView = state.ViewDeviceList
	case "e":
		m.state.CurrentView = state.ViewDeviceEdit
		m.state.SelectedFieldIdx = 0
	case "d":
		// Delete device
		file := m.state.CurrentFile()
		if file != nil && len(file.Modified.DeviceTypes) > 0 {
			idx := m.state.SelectedDeviceIdx
			file.Modified.DeviceTypes = append(
				file.Modified.DeviceTypes[:idx],
				file.Modified.DeviceTypes[idx+1:]...,
			)
			if m.state.SelectedDeviceIdx >= len(file.Modified.DeviceTypes) {
				m.state.SelectedDeviceIdx = len(file.Modified.DeviceTypes) - 1
			}
			if m.state.SelectedDeviceIdx < 0 {
				m.state.SelectedDeviceIdx = 0
			}
			m.state.MarkFileChanged()
			m.state.CurrentView = state.ViewDeviceList
		}
	}
	return nil
}

func (m *Model) handleDeviceEditKeys(key string) tea.Cmd {
	fields := m.getEditableFields()

	switch key {
	case "up", "k":
		if m.state.SelectedFieldIdx > 0 {
			m.state.SelectedFieldIdx--
		}
	case "down", "j":
		if m.state.SelectedFieldIdx < len(fields)-1 {
			m.state.SelectedFieldIdx++
		}
	case "enter":
		if m.state.SelectedFieldIdx < len(fields) {
			field := fields[m.state.SelectedFieldIdx]
			// Check if this is a config field that needs YAML editor
			switch field.name {
			case "technology_config", "control_config", "processor_config":
				m.openConfigEditor(field.name)
				return nil
			default:
				m.state.IsEditing = true
				m.state.EditingField = field.name
				m.input.SetValue(field.value)
				m.input.Focus()
			}
		}
	case "esc", "backspace":
		m.state.CurrentView = state.ViewDeviceDetail
	case "tab":
		// Cycle through select fields
		if m.state.SelectedFieldIdx < len(fields) {
			field := fields[m.state.SelectedFieldIdx]
			if field.options != nil {
				m.cycleFieldOption(field)
			}
		}
	}
	return nil
}

func (m *Model) handleConfirmSaveKeys(key string) tea.Cmd {
	switch key {
	case "esc":
		m.state.CurrentView = state.ViewVendorList
	case "enter", "y":
		return m.saveChanges()
	case "n":
		m.state.CurrentView = state.ViewVendorList
	}
	return nil
}

type editableField struct {
	name    string
	value   string
	options []string
}

func (m *Model) getEditableFields() []editableField {
	device := m.state.CurrentDevice()
	if device == nil {
		return nil
	}

	// Format controllable as string
	controllableStr := "false"
	if device.IsControllable() {
		controllableStr = "true"
	}

	fields := []editableField{
		{"vendor_name", device.VendorName, nil},
		{"model_number", device.ModelNumber, nil},
		{"name", device.Name, nil},
		{"device_type", device.DeviceType, models.DeviceTypeValues},
		{"description", device.Description, nil},
		{"technology", device.GetTechnology(), models.TechnologyValues},
		{"controllable", controllableStr, models.BooleanValues},
		{"decoder_type", device.GetDecoderType(), nil},
		{"technology_config", "[Edit YAML...]", nil},
		{"control_config", "[Edit YAML...]", nil},
		{"processor_config", "[Edit YAML...]", nil},
	}

	return fields
}

func (m *Model) cycleFieldOption(field editableField) {
	device := m.state.CurrentDevice()
	if device == nil || field.options == nil {
		return
	}

	currentIdx := 0
	for i, opt := range field.options {
		if opt == field.value {
			currentIdx = i
			break
		}
	}
	nextIdx := (currentIdx + 1) % len(field.options)
	newValue := field.options[nextIdx]

	m.applyFieldValue(field.name, newValue)
	m.state.MarkFileChanged()
}

func (m *Model) applyEdit() {
	newValue := m.input.Value()
	m.applyFieldValue(m.state.EditingField, newValue)
	m.state.MarkFileChanged()
}

func (m *Model) applyFieldValue(fieldName, value string) {
	device := m.state.CurrentDevice()
	if device == nil {
		return
	}

	switch fieldName {
	case "vendor_name":
		device.VendorName = value
	case "model_number":
		device.ModelNumber = value
	case "name":
		device.Name = value
	case "device_type":
		device.DeviceType = value
	case "description":
		device.Description = value
	case "technology":
		device.SetTechnology(value)
	case "controllable":
		device.SetControllable(value == "true")
	case "decoder_type":
		device.SetDecoderType(value)
	}
}

func (m *Model) openConfigEditor(configName string) {
	device := m.state.CurrentDevice()
	if device == nil {
		return
	}

	var configData map[string]interface{}
	switch configName {
	case "technology_config":
		configData = device.TechnologyConfig
		m.editingCfg = "technology"
	case "control_config":
		configData = device.ControlConfig
		m.editingCfg = "control"
	case "processor_config":
		configData = device.ProcessorConfig
		m.editingCfg = "processor"
	}

	// Convert to YAML
	yamlBytes, err := yaml.Marshal(configData)
	if err != nil {
		m.status = "Error converting to YAML: " + err.Error()
		return
	}

	m.textarea.SetValue(string(yamlBytes))
	m.textarea.Focus()
	m.state.CurrentView = state.ViewEditConfig
}

func (m *Model) saveConfigFromEditor() error {
	device := m.state.CurrentDevice()
	if device == nil {
		return fmt.Errorf("no device selected")
	}

	// Parse YAML from textarea
	var configData map[string]interface{}
	if err := yaml.Unmarshal([]byte(m.textarea.Value()), &configData); err != nil {
		return fmt.Errorf("invalid YAML: %w", err)
	}

	// Apply to device
	switch m.editingCfg {
	case "technology":
		device.TechnologyConfig = configData
	case "control":
		device.ControlConfig = configData
	case "processor":
		device.ProcessorConfig = configData
	}

	m.state.MarkFileChanged()
	return nil
}

func (m *Model) handleEditConfigKeys(key string) tea.Cmd {
	switch key {
	case "esc":
		m.state.CurrentView = state.ViewDeviceEdit
		return nil
	case "ctrl+s":
		if err := m.saveConfigFromEditor(); err != nil {
			m.status = "Error: " + err.Error()
		} else {
			m.status = "Config saved"
			m.state.CurrentView = state.ViewDeviceEdit
		}
		return nil
	}
	return nil
}

func (m *Model) saveChanges() tea.Cmd {
	return func() tea.Msg {
		changedFiles := m.state.GetChangedFiles()

		if m.localMode {
			// Local mode: save directly to filesystem
			for _, f := range changedFiles {
				content, err := state.SerializeFile(f.Modified)
				if err != nil {
					return errorMsg{fmt.Errorf("failed to serialize %s: %w", f.Path, err)}
				}

				if err := m.local.SaveFile(f.Path, content); err != nil {
					return errorMsg{fmt.Errorf("failed to save %s: %w", f.Path, err)}
				}
			}
			return filesSavedMsg{count: len(changedFiles)}
		}

		// GitHub mode: create PR
		files := make(map[string]source.FileChange)
		for _, f := range changedFiles {
			content, err := state.SerializeFile(f.Modified)
			if err != nil {
				return errorMsg{fmt.Errorf("failed to serialize %s: %w", f.Path, err)}
			}
			files[f.Path] = source.FileChange{
				Content: content,
				SHA:     f.SHA,
			}
		}

		title := "Update device definitions via sparkctl"
		body := "This PR was created using sparkctl.\n\n## Changes\n"
		for _, f := range changedFiles {
			body += fmt.Sprintf("- Updated `%s`\n", f.Path)
		}

		url, err := m.ghClient.CreatePRFromChanges(title, body, files)
		if err != nil {
			return errorMsg{fmt.Errorf("failed to create PR: %w", err)}
		}

		return prCreatedMsg{url}
	}
}

// View renders the TUI
func (m Model) View() string {
	var content string

	switch m.state.CurrentView {
	case state.ViewLoading:
		content = m.renderLoading()
	case state.ViewVendorList:
		content = m.renderVendorList()
	case state.ViewDeviceList:
		content = m.renderDeviceList()
	case state.ViewDeviceDetail:
		content = m.renderDeviceDetail()
	case state.ViewDeviceEdit:
		content = m.renderDeviceEdit()
	case state.ViewEditConfig:
		content = m.renderEditConfig()
	case state.ViewConfirmPR:
		content = m.renderConfirmSave()
	case state.ViewError:
		content = m.renderError()
	}

	// Add status bar
	status := m.renderStatusBar()

	return lipgloss.JoinVertical(lipgloss.Left, content, status)
}

func (m Model) renderLoading() string {
	return fmt.Sprintf("\n  %s Loading...\n", m.spinner.View())
}

func (m Model) renderVendorList() string {
	var b strings.Builder

	b.WriteString(titleStyle.Render("ENEROOO Spark Device Library"))
	b.WriteString("\n")
	b.WriteString(subtitleStyle.Render("Select a vendor to browse devices"))
	b.WriteString("\n\n")

	if m.state.Manifest != nil {
		for i, vendor := range m.state.Manifest.Vendors {
			cursor := "  "
			style := listItemStyle
			if i == m.state.SelectedVendorIdx {
				cursor = "> "
				style = selectedItemStyle
			}

			line := fmt.Sprintf("%s%s", cursor, vendor.Name)

			// Show technologies
			techs := strings.Join(vendor.Technologies, ", ")
			line += "  " + lipgloss.NewStyle().Foreground(mutedColor).Render(fmt.Sprintf("(%s)", techs))

			// Show changed indicator
			if f, ok := m.state.Files["devices/"+vendor.File]; ok && f.HasChanges {
				line += "  " + changedBadge.Render("MODIFIED")
			}

			b.WriteString(style.Render(line))
			b.WriteString("\n")
		}
	}

	b.WriteString("\n")
	help := "↑/↓ navigate • enter select"
	if m.state.HasPendingChanges() {
		if m.localMode {
			help += " • s save"
		} else {
			help += " • p create PR"
		}
	}
	help += " • q quit"
	b.WriteString(helpStyle.Render(help))

	return b.String()
}

func (m Model) renderDeviceList() string {
	var b strings.Builder

	vendor := m.state.CurrentVendor()
	file := m.state.CurrentFile()

	if vendor == nil || file == nil || file.Modified == nil {
		return "Loading..."
	}

	b.WriteString(titleStyle.Render(vendor.Name + " Devices"))
	b.WriteString("\n")
	b.WriteString(subtitleStyle.Render(fmt.Sprintf("%d devices", len(file.Modified.DeviceTypes))))
	b.WriteString("\n\n")

	for i, device := range file.Modified.DeviceTypes {
		cursor := "  "
		style := listItemStyle
		if i == m.state.SelectedDeviceIdx {
			cursor = "> "
			style = selectedItemStyle
		}

		line := fmt.Sprintf("%s%s (%s)", cursor, device.Name, device.ModelNumber)
		line += "  " + technologyBadge.Render(device.GetTechnology())

		b.WriteString(style.Render(line))
		b.WriteString("\n")
	}

	b.WriteString("\n")
	b.WriteString(helpStyle.Render("↑/↓ navigate • enter view • n new • esc back"))

	return b.String()
}

func (m Model) renderDeviceDetail() string {
	var b strings.Builder

	device := m.state.CurrentDevice()
	if device == nil {
		return "No device selected"
	}

	b.WriteString(titleStyle.Render(device.Name))
	b.WriteString("\n\n")

	// Basic info
	controllableStr := "No"
	if device.IsControllable() {
		controllableStr = "Yes"
	}

	fields := []struct {
		label string
		value string
	}{
		{"Vendor", device.VendorName},
		{"Model", device.ModelNumber},
		{"Type", device.DeviceType},
		{"Description", device.Description},
		{"Technology", device.GetTechnology()},
		{"Controllable", controllableStr},
		{"Decoder", device.GetDecoderType()},
	}

	for _, f := range fields {
		b.WriteString(labelStyle.Render(f.label + ":"))
		b.WriteString(valueStyle.Render(f.value))
		b.WriteString("\n")
	}

	// Technology-specific info
	b.WriteString("\n")
	tech := device.GetTechnology()
	switch tech {
	case "modbus":
		if regs, ok := device.TechnologyConfig["register_definitions"].([]interface{}); ok {
			b.WriteString(subtitleStyle.Render(fmt.Sprintf("%d register definitions", len(regs))))
		}
	case "lorawan":
		if class, ok := device.TechnologyConfig["device_class"].(string); ok && class != "" {
			b.WriteString(subtitleStyle.Render("Class " + class))
		}
	case "wmbus":
		if mfr, ok := device.TechnologyConfig["manufacturer_code"].(string); ok && mfr != "" {
			b.WriteString(subtitleStyle.Render("Manufacturer: " + mfr))
		}
	}

	b.WriteString("\n\n")
	b.WriteString(helpStyle.Render("e edit • d delete • esc back"))

	return b.String()
}

func (m Model) renderDeviceEdit() string {
	var b strings.Builder

	device := m.state.CurrentDevice()
	if device == nil {
		return "No device selected"
	}

	b.WriteString(titleStyle.Render("Edit: " + device.Name))
	b.WriteString("\n\n")

	fields := m.getEditableFields()

	for i, field := range fields {
		cursor := "  "
		style := listItemStyle
		if i == m.state.SelectedFieldIdx {
			cursor = "> "
			style = selectedItemStyle
		}

		label := labelStyle.Render(field.name + ":")
		var value string

		if m.state.IsEditing && i == m.state.SelectedFieldIdx {
			value = m.input.View()
		} else {
			if field.options != nil {
				value = editableValueStyle.Render(field.value + " [tab to cycle]")
			} else {
				value = editableValueStyle.Render(field.value)
			}
		}

		b.WriteString(style.Render(fmt.Sprintf("%s%s %s", cursor, label, value)))
		b.WriteString("\n")
	}

	b.WriteString("\n")
	if m.state.IsEditing {
		b.WriteString(helpStyle.Render("enter save • esc cancel"))
	} else {
		b.WriteString(helpStyle.Render("↑/↓ navigate • enter edit • tab cycle option • esc back"))
	}

	return b.String()
}

func (m Model) renderEditConfig() string {
	var b strings.Builder

	configName := ""
	switch m.editingCfg {
	case "technology":
		configName = "Technology Config"
	case "control":
		configName = "Control Config"
	case "processor":
		configName = "Processor Config"
	}

	b.WriteString(titleStyle.Render("Edit " + configName))
	b.WriteString("\n\n")

	b.WriteString(m.textarea.View())

	b.WriteString("\n\n")
	b.WriteString(helpStyle.Render("ctrl+s save • esc cancel"))

	return b.String()
}

func (m Model) renderConfirmSave() string {
	var b strings.Builder

	if m.localMode {
		b.WriteString(titleStyle.Render("Save Changes"))
	} else {
		b.WriteString(titleStyle.Render("Create Pull Request"))
	}
	b.WriteString("\n\n")

	b.WriteString("The following files have been modified:\n\n")

	for _, f := range m.state.GetChangedFiles() {
		b.WriteString(fmt.Sprintf("  • %s\n", f.Path))
	}

	b.WriteString("\n")
	if m.localMode {
		b.WriteString(boxStyle.Render("Save these changes to local files?"))
	} else {
		b.WriteString(boxStyle.Render("Create a PR with these changes?"))
	}
	b.WriteString("\n\n")
	b.WriteString(helpStyle.Render("y/enter confirm • n/esc cancel"))

	return b.String()
}

func (m Model) renderError() string {
	var b strings.Builder

	b.WriteString(errorStyle.Render("Error"))
	b.WriteString("\n\n")

	if m.state.Error != nil {
		b.WriteString(m.state.Error.Error())
	}

	b.WriteString("\n\n")
	b.WriteString(helpStyle.Render("esc/enter to continue"))

	return b.String()
}

func (m Model) renderStatusBar() string {
	if m.status == "" {
		return ""
	}
	return "\n" + statusStyle.Render(m.status)
}

// Deep copy helper
func deepCopyDeviceFile(src *models.DeviceFile) *models.DeviceFile {
	if src == nil {
		return nil
	}

	dst := &models.DeviceFile{
		DeviceTypes: make([]models.DeviceType, len(src.DeviceTypes)),
	}

	for i, device := range src.DeviceTypes {
		dst.DeviceTypes[i] = models.DeviceType{
			VendorName:       device.VendorName,
			ModelNumber:      device.ModelNumber,
			Name:             device.Name,
			DeviceType:       device.DeviceType,
			Description:      device.Description,
			TechnologyConfig: deepCopyMap(device.TechnologyConfig),
			ControlConfig:    deepCopyMap(device.ControlConfig),
			ProcessorConfig:  deepCopyMap(device.ProcessorConfig),
		}
	}

	return dst
}

// deepCopyMap creates a shallow copy of a map (sufficient for our use case)
func deepCopyMap(src map[string]interface{}) map[string]interface{} {
	if src == nil {
		return nil
	}
	dst := make(map[string]interface{}, len(src))
	for k, v := range src {
		dst[k] = v
	}
	return dst
}
