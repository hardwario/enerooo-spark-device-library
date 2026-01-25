package models

// DeviceFile represents a vendor's device definitions file
type DeviceFile struct {
	DeviceTypes []DeviceType `yaml:"device_types"`
}

// DeviceType represents a single device definition
type DeviceType struct {
	VendorName       string                 `yaml:"vendor_name"`
	ModelNumber      string                 `yaml:"model_number"`
	Name             string                 `yaml:"name"`
	DeviceType       string                 `yaml:"device_type"`
	Description      string                 `yaml:"description,omitempty"`
	TechnologyConfig map[string]interface{} `yaml:"technology_config"`
	ControlConfig    map[string]interface{} `yaml:"control_config,omitempty"`
	ProcessorConfig  map[string]interface{} `yaml:"processor_config,omitempty"`
}

// GetTechnology returns the technology from the config
func (d *DeviceType) GetTechnology() string {
	if tech, ok := d.TechnologyConfig["technology"].(string); ok {
		return tech
	}
	return ""
}

// SetTechnology sets the technology in the config
func (d *DeviceType) SetTechnology(tech string) {
	if d.TechnologyConfig == nil {
		d.TechnologyConfig = make(map[string]interface{})
	}
	d.TechnologyConfig["technology"] = tech
}

// IsControllable returns whether the device is controllable
func (d *DeviceType) IsControllable() bool {
	if d.ControlConfig == nil {
		return false
	}
	if ctrl, ok := d.ControlConfig["controllable"].(bool); ok {
		return ctrl
	}
	return false
}

// SetControllable sets the controllable flag
func (d *DeviceType) SetControllable(controllable bool) {
	if d.ControlConfig == nil {
		d.ControlConfig = make(map[string]interface{})
	}
	d.ControlConfig["controllable"] = controllable
}

// GetDecoderType returns the decoder type from processor config
func (d *DeviceType) GetDecoderType() string {
	if d.ProcessorConfig == nil {
		return ""
	}
	if dec, ok := d.ProcessorConfig["decoder_type"].(string); ok {
		return dec
	}
	return ""
}

// SetDecoderType sets the decoder type in processor config
func (d *DeviceType) SetDecoderType(decoderType string) {
	if d.ProcessorConfig == nil {
		d.ProcessorConfig = make(map[string]interface{})
	}
	if decoderType == "" {
		delete(d.ProcessorConfig, "decoder_type")
	} else {
		d.ProcessorConfig["decoder_type"] = decoderType
	}
}

// Manifest represents the manifest.yaml file
type Manifest struct {
	Version       string        `yaml:"version"`
	Released      string        `yaml:"released,omitempty"`
	SchemaVersion int           `yaml:"schema_version"`
	Vendors       []VendorEntry `yaml:"vendors"`
}

// VendorEntry in the manifest
type VendorEntry struct {
	Name         string   `yaml:"name"`
	File         string   `yaml:"file"`
	Technologies []string `yaml:"technologies,omitempty"`
}

// DeviceTypeValues for dropdown selections
var DeviceTypeValues = []string{
	"power_meter",
	"gateway",
	"environment_sensor",
	"water_meter",
	"heat_meter",
}

// TechnologyValues for dropdown selections
var TechnologyValues = []string{
	"modbus",
	"lorawan",
	"wmbus",
}

// BooleanValues for yes/no dropdowns
var BooleanValues = []string{
	"true",
	"false",
}
