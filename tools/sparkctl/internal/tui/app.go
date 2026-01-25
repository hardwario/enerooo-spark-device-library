package tui

import (
	"fmt"
	"strconv"
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
	case state.ViewRegisterList:
		return m.handleRegisterListKeys(key)
	case state.ViewRegisterEdit:
		return m.handleRegisterEditKeys(key)
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
			case "registers":
				m.state.SelectedRegisterIdx = 0
				m.state.CurrentView = state.ViewRegisterList
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

func (m *Model) handleRegisterListKeys(key string) tea.Cmd {
	device := m.state.CurrentDevice()
	if device == nil {
		return nil
	}

	regs := device.GetRegisterDefinitions()
	regCount := len(regs)

	switch key {
	case "up", "k":
		if m.state.SelectedRegisterIdx > 0 {
			m.state.SelectedRegisterIdx--
		}
	case "down", "j":
		if m.state.SelectedRegisterIdx < regCount-1 {
			m.state.SelectedRegisterIdx++
		}
	case "enter", "e":
		if regCount > 0 {
			m.openRegisterEditor()
		}
	case "n":
		// Add new register
		newReg := models.NewRegisterDefinition()
		regs = append(regs, newReg)
		device.SetRegisterDefinitions(regs)
		m.state.SelectedRegisterIdx = len(regs) - 1
		m.state.MarkFileChanged()
		m.openRegisterEditor()
	case "d":
		// Delete selected register
		if regCount > 0 {
			idx := m.state.SelectedRegisterIdx
			regs = append(regs[:idx], regs[idx+1:]...)
			device.SetRegisterDefinitions(regs)
			if m.state.SelectedRegisterIdx >= len(regs) && len(regs) > 0 {
				m.state.SelectedRegisterIdx = len(regs) - 1
			}
			m.state.MarkFileChanged()
		}
	case "esc", "backspace":
		m.state.CurrentView = state.ViewDeviceEdit
	}
	return nil
}

func (m *Model) handleRegisterEditKeys(key string) tea.Cmd {
	fields := m.getRegisterEditFields()

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
			m.state.IsEditing = true
			m.state.EditingField = field.name
			m.input.SetValue(field.value)
			m.input.Focus()
		}
	case "tab":
		if m.state.SelectedFieldIdx < len(fields) {
			field := fields[m.state.SelectedFieldIdx]
			if field.options != nil {
				m.cycleRegisterFieldOption(field)
			}
		}
	case "esc", "backspace":
		m.state.CurrentView = state.ViewRegisterList
		m.state.SelectedFieldIdx = 0
	}
	return nil
}

func (m *Model) openRegisterEditor() {
	m.state.SelectedFieldIdx = 0
	m.state.CurrentView = state.ViewRegisterEdit
}

func (m *Model) getRegisterEditFields() []editableField {
	device := m.state.CurrentDevice()
	if device == nil {
		return nil
	}

	regs := device.GetRegisterDefinitions()
	if m.state.SelectedRegisterIdx >= len(regs) {
		return nil
	}

	reg := regs[m.state.SelectedRegisterIdx]

	// Extract field values with type assertions
	fieldName := ""
	fieldUnit := ""
	if field, ok := reg["field"].(map[string]interface{}); ok {
		if name, ok := field["name"].(string); ok {
			fieldName = name
		}
		if unit, ok := field["unit"].(string); ok {
			fieldUnit = unit
		}
	}

	address := 0
	if addr, ok := reg["address"].(int); ok {
		address = addr
	}

	dataType := "uint16"
	if dt, ok := reg["data_type"].(string); ok {
		dataType = dt
	}

	scale := 1.0
	if s, ok := reg["scale"].(float64); ok {
		scale = s
	} else if s, ok := reg["scale"].(int); ok {
		scale = float64(s)
	}

	offset := 0.0
	if o, ok := reg["offset"].(float64); ok {
		offset = o
	} else if o, ok := reg["offset"].(int); ok {
		offset = float64(o)
	}

	return []editableField{
		{"field_name", fieldName, nil},
		{"field_unit", fieldUnit, nil},
		{"address", fmt.Sprintf("%d", address), nil},
		{"data_type", dataType, models.DataTypeValues},
		{"scale", fmt.Sprintf("%.6g", scale), nil},
		{"offset", fmt.Sprintf("%.6g", offset), nil},
	}
}

func (m *Model) cycleRegisterFieldOption(field editableField) {
	if field.options == nil {
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

	m.applyRegisterFieldValue(field.name, newValue)
	m.state.MarkFileChanged()
}

func (m *Model) applyRegisterFieldValue(fieldName, value string) {
	device := m.state.CurrentDevice()
	if device == nil {
		return
	}

	regs := device.GetRegisterDefinitions()
	if m.state.SelectedRegisterIdx >= len(regs) {
		return
	}

	reg := regs[m.state.SelectedRegisterIdx]

	switch fieldName {
	case "field_name":
		if field, ok := reg["field"].(map[string]interface{}); ok {
			field["name"] = value
		} else {
			reg["field"] = map[string]interface{}{"name": value, "unit": ""}
		}
	case "field_unit":
		if field, ok := reg["field"].(map[string]interface{}); ok {
			field["unit"] = value
		} else {
			reg["field"] = map[string]interface{}{"name": "", "unit": value}
		}
	case "address":
		if addr, err := strconv.Atoi(value); err == nil {
			reg["address"] = addr
		}
	case "data_type":
		reg["data_type"] = value
	case "scale":
		if s, err := strconv.ParseFloat(value, 64); err == nil {
			reg["scale"] = s
		}
	case "offset":
		if o, err := strconv.ParseFloat(value, 64); err == nil {
			reg["offset"] = o
		}
	}

	device.SetRegisterDefinitions(regs)
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
	}

	// Add register definitions editor for Modbus devices
	if device.GetTechnology() == "modbus" {
		regs := device.GetRegisterDefinitions()
		regCount := len(regs)
		fields = append(fields, editableField{
			"registers",
			fmt.Sprintf("[%d registers - Edit...]", regCount),
			nil,
		})
	}

	// Add config editors
	fields = append(fields,
		editableField{"technology_config", "[Edit YAML...]", nil},
		editableField{"control_config", "[Edit YAML...]", nil},
		editableField{"processor_config", "[Edit YAML...]", nil},
	)

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
	if m.state.CurrentView == state.ViewRegisterEdit {
		m.applyRegisterFieldValue(m.state.EditingField, newValue)
	} else {
		m.applyFieldValue(m.state.EditingField, newValue)
	}
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
	width := m.width
	if width < minWidth {
		width = minWidth
	}

	// Build the layout
	header := m.renderHeader(width)
	content := m.renderContent(width)
	footer := m.renderFooter(width)

	return lipgloss.JoinVertical(lipgloss.Left, header, content, footer)
}

func (m Model) renderHeader(width int) string {
	// Logo
	logo := logoStyle.Render("⚡ SPARKCTL")

	// Breadcrumb
	breadcrumb := m.getBreadcrumb()

	// Mode indicator
	var mode string
	if m.localMode {
		mode = modeLocalStyle.Render("LOCAL")
	} else {
		mode = modeGitHubStyle.Render("GITHUB")
	}

	// Calculate spacing
	leftPart := logo + "  " + breadcrumb
	rightPart := mode

	// Create the header with proper spacing
	spacing := width - lipgloss.Width(leftPart) - lipgloss.Width(rightPart) - 6
	if spacing < 1 {
		spacing = 1
	}
	spacer := strings.Repeat(" ", spacing)

	headerContent := leftPart + spacer + rightPart
	return headerStyle.Width(width - 2).Render(headerContent)
}

func (m Model) getBreadcrumb() string {
	parts := []string{}

	switch m.state.CurrentView {
	case state.ViewVendorList:
		parts = append(parts, breadcrumbActiveStyle.Render("Vendors"))
	case state.ViewDeviceList:
		parts = append(parts, breadcrumbStyle.Render("Vendors"))
		if v := m.state.CurrentVendor(); v != nil {
			parts = append(parts, breadcrumbActiveStyle.Render(v.Name))
		}
	case state.ViewDeviceDetail, state.ViewDeviceEdit, state.ViewEditConfig:
		parts = append(parts, breadcrumbStyle.Render("Vendors"))
		if v := m.state.CurrentVendor(); v != nil {
			parts = append(parts, breadcrumbStyle.Render(v.Name))
		}
		if d := m.state.CurrentDevice(); d != nil {
			parts = append(parts, breadcrumbActiveStyle.Render(d.Name))
		}
	case state.ViewRegisterList, state.ViewRegisterEdit:
		parts = append(parts, breadcrumbStyle.Render("Vendors"))
		if v := m.state.CurrentVendor(); v != nil {
			parts = append(parts, breadcrumbStyle.Render(v.Name))
		}
		if d := m.state.CurrentDevice(); d != nil {
			parts = append(parts, breadcrumbStyle.Render(d.Name))
		}
		parts = append(parts, breadcrumbActiveStyle.Render("Registers"))
	case state.ViewConfirmPR:
		parts = append(parts, breadcrumbActiveStyle.Render("Save Changes"))
	case state.ViewError:
		parts = append(parts, breadcrumbActiveStyle.Render("Error"))
	default:
		parts = append(parts, breadcrumbActiveStyle.Render("Loading"))
	}

	sep := breadcrumbStyle.Render(" " + IconArrowRight + " ")
	return strings.Join(parts, sep)
}

func (m Model) renderContent(width int) string {
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
	case state.ViewRegisterList:
		content = m.renderRegisterList()
	case state.ViewRegisterEdit:
		content = m.renderRegisterEdit()
	case state.ViewConfirmPR:
		content = m.renderConfirmSave()
	case state.ViewError:
		content = m.renderError()
	}

	return panelStyle.Width(width - 2).Render(content)
}

func (m Model) renderFooter(width int) string {
	// Help keys for current view
	help := m.getHelpText()

	// Status/changes info
	var status string
	if m.status != "" {
		status = statusStyle.Render(m.status)
	}

	changesCount := len(m.state.GetChangedFiles())
	var changesText string
	if changesCount > 0 {
		changesText = changesCountStyle.Render(fmt.Sprintf("%s %d changed", IconModified, changesCount))
	}

	// Build footer
	rightPart := ""
	if changesText != "" {
		rightPart = changesText
	}
	if status != "" {
		if rightPart != "" {
			rightPart = status + "  " + rightPart
		} else {
			rightPart = status
		}
	}

	spacing := width - lipgloss.Width(help) - lipgloss.Width(rightPart) - 6
	if spacing < 1 {
		spacing = 1
	}
	spacer := strings.Repeat(" ", spacing)

	footerContent := help + spacer + rightPart
	return footerStyle.Width(width - 2).Render(footerContent)
}

func (m Model) getHelpText() string {
	var keys []string

	switch m.state.CurrentView {
	case state.ViewVendorList:
		keys = append(keys, m.helpKey("↑↓", "navigate"), m.helpKey("⏎", "select"))
		if m.state.HasPendingChanges() {
			if m.localMode {
				keys = append(keys, m.helpKey("s", "save"))
			} else {
				keys = append(keys, m.helpKey("p", "create PR"))
			}
		}
		keys = append(keys, m.helpKey("q", "quit"))
	case state.ViewDeviceList:
		keys = append(keys, m.helpKey("↑↓", "navigate"), m.helpKey("⏎", "view"), m.helpKey("n", "new"), m.helpKey("esc", "back"))
	case state.ViewDeviceDetail:
		keys = append(keys, m.helpKey("e", "edit"), m.helpKey("d", "delete"), m.helpKey("esc", "back"))
	case state.ViewDeviceEdit:
		if m.state.IsEditing {
			keys = append(keys, m.helpKey("⏎", "save"), m.helpKey("esc", "cancel"))
		} else {
			keys = append(keys, m.helpKey("↑↓", "navigate"), m.helpKey("⏎", "edit"), m.helpKey("tab", "cycle"), m.helpKey("esc", "back"))
		}
	case state.ViewEditConfig:
		keys = append(keys, m.helpKey("ctrl+s", "save"), m.helpKey("esc", "cancel"))
	case state.ViewRegisterList:
		keys = append(keys, m.helpKey("↑↓", "navigate"), m.helpKey("⏎", "edit"), m.helpKey("n", "new"), m.helpKey("d", "delete"), m.helpKey("esc", "back"))
	case state.ViewRegisterEdit:
		if m.state.IsEditing {
			keys = append(keys, m.helpKey("⏎", "save"), m.helpKey("esc", "cancel"))
		} else {
			keys = append(keys, m.helpKey("↑↓", "navigate"), m.helpKey("⏎", "edit"), m.helpKey("tab", "cycle"), m.helpKey("esc", "back"))
		}
	case state.ViewConfirmPR:
		keys = append(keys, m.helpKey("y", "confirm"), m.helpKey("n", "cancel"))
	case state.ViewError:
		keys = append(keys, m.helpKey("⏎", "continue"))
	}

	return strings.Join(keys, "  ")
}

func (m Model) helpKey(key, desc string) string {
	return helpKeyStyle.Render(key) + " " + helpDescStyle.Render(desc)
}

func (m Model) renderLoading() string {
	return fmt.Sprintf("\n\n  %s Loading from %s...\n\n", m.spinner.View(),
		func() string {
			if m.localMode {
				return "local filesystem"
			}
			return "GitHub"
		}())
}

func (m Model) renderVendorList() string {
	var b strings.Builder

	b.WriteString(panelTitleStyle.Render("Select a vendor to browse devices"))
	b.WriteString("\n\n")

	if m.state.Manifest != nil {
		for i, vendor := range m.state.Manifest.Vendors {
			var line string
			isSelected := i == m.state.SelectedVendorIdx

			if isSelected {
				line = IconSelected + " "
			} else {
				line = IconUnselected + " "
			}

			line += IconFolder + " " + vendor.Name

			// Show technologies as badges
			if len(vendor.Technologies) > 0 {
				line += "  "
				for _, tech := range vendor.Technologies {
					line += techBadgeStyle(tech).Render(tech) + " "
				}
			}

			// Show changed indicator
			if f, ok := m.state.Files["devices/"+vendor.File]; ok && f.HasChanges {
				line += " " + badgeModifiedStyle.Render("MODIFIED")
			}

			if isSelected {
				b.WriteString(listItemSelectedStyle.Render(line))
			} else {
				b.WriteString(listItemStyle.Render(line))
			}
			b.WriteString("\n")
		}
	}

	return b.String()
}

func (m Model) renderDeviceList() string {
	var b strings.Builder

	vendor := m.state.CurrentVendor()
	file := m.state.CurrentFile()

	if vendor == nil || file == nil || file.Modified == nil {
		return "Loading..."
	}

	b.WriteString(panelTitleStyle.Render(fmt.Sprintf("%d devices", len(file.Modified.DeviceTypes))))
	b.WriteString("\n\n")

	for i, device := range file.Modified.DeviceTypes {
		var line string
		isSelected := i == m.state.SelectedDeviceIdx

		if isSelected {
			line = IconSelected + " "
		} else {
			line = IconUnselected + " "
		}

		// Device icon and name
		line += deviceTypeIcon(device.DeviceType) + " "
		line += device.Name
		line += "  " + badgeDeviceTypeStyle.Render(device.ModelNumber)

		// Technology badge
		tech := device.GetTechnology()
		if tech != "" {
			line += "  " + techBadgeStyle(tech).Render(tech)
		}

		// Controllable indicator
		if device.IsControllable() {
			line += "  " + badgeControllableStyle.Render(IconControllable + " controllable")
		}

		if isSelected {
			b.WriteString(listItemSelectedStyle.Render(line))
		} else {
			b.WriteString(listItemStyle.Render(line))
		}
		b.WriteString("\n")
	}

	return b.String()
}

func (m Model) renderDeviceDetail() string {
	var b strings.Builder

	device := m.state.CurrentDevice()
	if device == nil {
		return "No device selected"
	}

	// Header with icon
	header := deviceTypeIcon(device.DeviceType) + " " + panelTitleStyle.Render(device.Name)
	if device.IsControllable() {
		header += "  " + badgeControllableStyle.Render(IconControllable + " controllable")
	}
	b.WriteString(header)
	b.WriteString("\n")
	b.WriteString(panelSubtitleStyle.Render(device.ModelNumber + " • " + device.VendorName))
	b.WriteString("\n\n")

	// Info grid
	fields := []struct {
		label string
		value string
	}{
		{"Type", device.DeviceType},
		{"Technology", device.GetTechnology()},
		{"Description", device.Description},
		{"Decoder", device.GetDecoderType()},
	}

	for _, f := range fields {
		if f.value != "" {
			b.WriteString(labelStyle.Render(f.label + ":"))
			b.WriteString(valueStyle.Render(f.value))
			b.WriteString("\n")
		}
	}

	// Technology-specific info
	b.WriteString("\n")
	tech := device.GetTechnology()
	switch tech {
	case "modbus":
		if regs, ok := device.TechnologyConfig["register_definitions"].([]interface{}); ok {
			b.WriteString(panelSubtitleStyle.Render(fmt.Sprintf("📊 %d register definitions", len(regs))))
		}
	case "lorawan":
		if class, ok := device.TechnologyConfig["device_class"].(string); ok && class != "" {
			b.WriteString(panelSubtitleStyle.Render("📡 Class " + class))
		}
	case "wmbus":
		if mfr, ok := device.TechnologyConfig["manufacturer_code"].(string); ok && mfr != "" {
			b.WriteString(panelSubtitleStyle.Render("📻 Manufacturer: " + mfr))
		}
	}

	return b.String()
}

func (m Model) renderDeviceEdit() string {
	var b strings.Builder

	device := m.state.CurrentDevice()
	if device == nil {
		return "No device selected"
	}

	b.WriteString(panelTitleStyle.Render("Editing Device"))
	b.WriteString("\n\n")

	fields := m.getEditableFields()

	for i, field := range fields {
		isSelected := i == m.state.SelectedFieldIdx
		var line string

		if isSelected {
			line = IconSelected + " "
		} else {
			line = IconUnselected + " "
		}

		line += labelStyle.Render(field.name + ":")

		var value string
		if m.state.IsEditing && isSelected {
			value = m.input.View()
		} else {
			if field.options != nil {
				value = valueEditableStyle.Render(field.value) + " " + helpKeyStyle.Render("[tab]")
			} else if strings.HasPrefix(field.value, "[Edit") {
				value = helpDescStyle.Render(field.value)
			} else {
				value = valueEditableStyle.Render(field.value)
			}
		}

		line += " " + value

		if isSelected {
			b.WriteString(listItemSelectedStyle.Render(line))
		} else {
			b.WriteString(listItemStyle.Render(line))
		}
		b.WriteString("\n")
	}

	return b.String()
}

func (m Model) renderEditConfig() string {
	var b strings.Builder

	configName := ""
	icon := "📝"
	switch m.editingCfg {
	case "technology":
		configName = "Technology Config"
		icon = "⚙️"
	case "control":
		configName = "Control Config"
		icon = "🎮"
	case "processor":
		configName = "Processor Config"
		icon = "🔧"
	}

	b.WriteString(panelTitleStyle.Render(icon + " " + configName))
	b.WriteString("\n")
	b.WriteString(panelSubtitleStyle.Render("Edit YAML configuration directly"))
	b.WriteString("\n\n")

	b.WriteString(m.textarea.View())

	return b.String()
}

func (m Model) renderRegisterList() string {
	var b strings.Builder

	device := m.state.CurrentDevice()
	if device == nil {
		return "No device selected"
	}

	regs := device.GetRegisterDefinitions()

	b.WriteString(panelTitleStyle.Render("📊 Register Definitions"))
	b.WriteString("\n")
	b.WriteString(panelSubtitleStyle.Render(fmt.Sprintf("%d registers • Modbus device", len(regs))))
	b.WriteString("\n\n")

	if len(regs) == 0 {
		b.WriteString(listItemDimStyle.Render("No registers defined. Press 'n' to add one."))
		b.WriteString("\n")
	} else {
		for i, reg := range regs {
			isSelected := i == m.state.SelectedRegisterIdx
			var line string

			if isSelected {
				line = IconSelected + " "
			} else {
				line = IconUnselected + " "
			}

			// Extract register info
			fieldName := "unnamed"
			fieldUnit := ""
			if field, ok := reg["field"].(map[string]interface{}); ok {
				if name, ok := field["name"].(string); ok && name != "" {
					fieldName = name
				}
				if unit, ok := field["unit"].(string); ok {
					fieldUnit = unit
				}
			}

			address := 0
			if addr, ok := reg["address"].(int); ok {
				address = addr
			}

			dataType := "uint16"
			if dt, ok := reg["data_type"].(string); ok {
				dataType = dt
			}

			// Format the line
			line += fmt.Sprintf("@%-5d ", address)
			line += badgeTechStyle.Render(dataType) + " "
			line += valueStyle.Render(fieldName)
			if fieldUnit != "" {
				line += " " + listItemDimStyle.Render("("+fieldUnit+")")
			}

			if isSelected {
				b.WriteString(listItemSelectedStyle.Render(line))
			} else {
				b.WriteString(listItemStyle.Render(line))
			}
			b.WriteString("\n")
		}
	}

	return b.String()
}

func (m Model) renderRegisterEdit() string {
	var b strings.Builder

	device := m.state.CurrentDevice()
	if device == nil {
		return "No device selected"
	}

	regs := device.GetRegisterDefinitions()
	if m.state.SelectedRegisterIdx >= len(regs) {
		return "No register selected"
	}

	b.WriteString(panelTitleStyle.Render("✏️  Edit Register"))
	b.WriteString("\n")
	b.WriteString(panelSubtitleStyle.Render(fmt.Sprintf("Register %d of %d", m.state.SelectedRegisterIdx+1, len(regs))))
	b.WriteString("\n\n")

	fields := m.getRegisterEditFields()

	for i, field := range fields {
		isSelected := i == m.state.SelectedFieldIdx
		var line string

		if isSelected {
			line = IconSelected + " "
		} else {
			line = IconUnselected + " "
		}

		// Format field name for display
		displayName := field.name
		switch field.name {
		case "field_name":
			displayName = "name"
		case "field_unit":
			displayName = "unit"
		}

		line += labelStyle.Render(displayName + ":")

		var value string
		if m.state.IsEditing && isSelected {
			value = m.input.View()
		} else {
			if field.options != nil {
				value = valueEditableStyle.Render(field.value) + " " + helpKeyStyle.Render("[tab]")
			} else {
				value = valueEditableStyle.Render(field.value)
			}
		}

		line += " " + value

		if isSelected {
			b.WriteString(listItemSelectedStyle.Render(line))
		} else {
			b.WriteString(listItemStyle.Render(line))
		}
		b.WriteString("\n")
	}

	return b.String()
}

func (m Model) renderConfirmSave() string {
	var b strings.Builder

	if m.localMode {
		b.WriteString(panelTitleStyle.Render("💾 Save Changes"))
	} else {
		b.WriteString(panelTitleStyle.Render("🚀 Create Pull Request"))
	}
	b.WriteString("\n\n")

	b.WriteString(valueStyle.Render("The following files will be updated:"))
	b.WriteString("\n\n")

	for _, f := range m.state.GetChangedFiles() {
		b.WriteString(listItemStyle.Render(IconModified + " " + f.Path))
		b.WriteString("\n")
	}

	b.WriteString("\n")
	if m.localMode {
		b.WriteString(boxStyle.Render("Save changes to local files?"))
	} else {
		b.WriteString(boxStyle.Render("Create a pull request with these changes?"))
	}

	return b.String()
}

func (m Model) renderError() string {
	var b strings.Builder

	b.WriteString(errorStyle.Render("⚠️  Error"))
	b.WriteString("\n\n")

	if m.state.Error != nil {
		b.WriteString(valueStyle.Render(m.state.Error.Error()))
	}

	return b.String()
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
