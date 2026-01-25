package source

import "github.com/hardwario/enerooo-spark-device-library/tools/sparkctl/internal/models"

// Source defines the interface for reading device library data
type Source interface {
	// FetchManifest retrieves the manifest
	FetchManifest() (*models.Manifest, error)

	// FetchDeviceFile retrieves a device file by path, returns file, SHA (for GitHub), and error
	FetchDeviceFile(path string) (*models.DeviceFile, string, error)

	// CanWrite returns true if this source supports writing changes
	CanWrite() bool

	// CreatePR creates a pull request with the given changes (only for GitHub)
	CreatePR(title, body string, files map[string]FileChange) (string, error)
}

// FileChange represents a file to be changed
type FileChange struct {
	Content string
	SHA     string // Original SHA for GitHub API
}
