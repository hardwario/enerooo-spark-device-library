package state

import (
	"github.com/hardwario/enerooo-spark-device-library/tools/sparkctl/internal/models"
	"gopkg.in/yaml.v3"
)

// View represents the current view in the TUI
type View int

const (
	ViewLoading View = iota
	ViewVendorList
	ViewDeviceList
	ViewDeviceDetail
	ViewDeviceEdit
	ViewEditConfig    // For editing control_config, technology_config, processor_config as YAML
	ViewRegisterList  // For viewing/managing Modbus register definitions
	ViewRegisterEdit  // For editing a single register
	ViewConfirmPR
	ViewError
)

// FileState tracks the state of a file
type FileState struct {
	Path       string
	SHA        string
	Original   *models.DeviceFile
	Modified   *models.DeviceFile
	HasChanges bool
}

// State holds the entire application state
type State struct {
	// Current view
	CurrentView View

	// Error message if any
	Error error

	// Manifest data
	Manifest        *models.Manifest
	ManifestChanged bool

	// Current navigation
	SelectedVendorIdx   int
	SelectedDeviceIdx   int
	SelectedFieldIdx    int
	SelectedRegisterIdx int

	// File states (keyed by file path)
	Files map[string]*FileState

	// Changes to upload
	PendingChanges []PendingChange

	// Editing state
	IsEditing    bool
	EditingField string
	EditBuffer   string
}

// PendingChange represents a change to be uploaded
type PendingChange struct {
	FilePath    string
	Description string
}

// NewState creates a new application state
func NewState() *State {
	return &State{
		CurrentView: ViewLoading,
		Files:       make(map[string]*FileState),
	}
}

// CurrentVendor returns the currently selected vendor
func (s *State) CurrentVendor() *models.VendorEntry {
	if s.Manifest == nil || s.SelectedVendorIdx >= len(s.Manifest.Vendors) {
		return nil
	}
	return &s.Manifest.Vendors[s.SelectedVendorIdx]
}

// CurrentFile returns the current file state
func (s *State) CurrentFile() *FileState {
	vendor := s.CurrentVendor()
	if vendor == nil {
		return nil
	}
	return s.Files["devices/"+vendor.File]
}

// CurrentDevice returns the currently selected device
func (s *State) CurrentDevice() *models.DeviceType {
	file := s.CurrentFile()
	if file == nil || file.Modified == nil {
		return nil
	}
	if s.SelectedDeviceIdx >= len(file.Modified.DeviceTypes) {
		return nil
	}
	return &file.Modified.DeviceTypes[s.SelectedDeviceIdx]
}

// MarkFileChanged marks the current file as having changes
func (s *State) MarkFileChanged() {
	file := s.CurrentFile()
	if file == nil {
		return
	}
	file.HasChanges = true
}

// HasPendingChanges returns true if any files have unsaved changes
func (s *State) HasPendingChanges() bool {
	if s.ManifestChanged {
		return true
	}
	for _, f := range s.Files {
		if f.HasChanges {
			return true
		}
	}
	return false
}

// GetChangedFiles returns all files with changes
func (s *State) GetChangedFiles() []*FileState {
	var changed []*FileState
	for _, f := range s.Files {
		if f.HasChanges {
			changed = append(changed, f)
		}
	}
	return changed
}

// SerializeFile serializes a device file to YAML
func SerializeFile(df *models.DeviceFile) (string, error) {
	data, err := yaml.Marshal(df)
	if err != nil {
		return "", err
	}
	return string(data), nil
}
