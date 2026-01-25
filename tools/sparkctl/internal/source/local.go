package source

import (
	"fmt"
	"os"
	"path/filepath"

	"github.com/hardwario/enerooo-spark-device-library/tools/sparkctl/internal/models"
	"gopkg.in/yaml.v3"
)

// LocalSource reads from the local filesystem
type LocalSource struct {
	BasePath string
}

// NewLocalSource creates a new local source
func NewLocalSource(basePath string) *LocalSource {
	return &LocalSource{BasePath: basePath}
}

// FetchManifest reads manifest.yaml from local filesystem
func (s *LocalSource) FetchManifest() (*models.Manifest, error) {
	path := filepath.Join(s.BasePath, "manifest.yaml")
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("failed to read manifest: %w", err)
	}

	var manifest models.Manifest
	if err := yaml.Unmarshal(data, &manifest); err != nil {
		return nil, fmt.Errorf("failed to parse manifest: %w", err)
	}

	return &manifest, nil
}

// FetchDeviceFile reads a device file from local filesystem
func (s *LocalSource) FetchDeviceFile(path string) (*models.DeviceFile, string, error) {
	fullPath := filepath.Join(s.BasePath, path)
	data, err := os.ReadFile(fullPath)
	if err != nil {
		return nil, "", fmt.Errorf("failed to read device file: %w", err)
	}

	var deviceFile models.DeviceFile
	if err := yaml.Unmarshal(data, &deviceFile); err != nil {
		return nil, "", fmt.Errorf("failed to parse device file: %w", err)
	}

	// Use file path as a pseudo-SHA for local files
	return &deviceFile, path, nil
}

// CanWrite returns true - local source can write directly
func (s *LocalSource) CanWrite() bool {
	return true
}

// CreatePR is not supported for local source - writes directly instead
func (s *LocalSource) CreatePR(title, body string, files map[string]FileChange) (string, error) {
	return "", fmt.Errorf("PR creation not supported in local mode - use SaveFiles instead")
}

// SaveFile writes a device file to the local filesystem
func (s *LocalSource) SaveFile(path, content string) error {
	fullPath := filepath.Join(s.BasePath, path)
	return os.WriteFile(fullPath, []byte(content), 0644)
}
