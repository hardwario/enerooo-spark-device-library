package github

import (
	"encoding/base64"
	"encoding/json"
	"fmt"
	"os/exec"
	"strings"
	"time"

	"github.com/hardwario/enerooo-spark-device-library/tools/sparkctl/internal/models"
	"github.com/hardwario/enerooo-spark-device-library/tools/sparkctl/internal/source"
	"gopkg.in/yaml.v3"
)

const (
	DefaultOwner = "hardwario"
	DefaultRepo  = "enerooo-spark-device-library"
)

// Client handles GitHub API operations via gh CLI
type Client struct {
	Owner string
	Repo  string
}

// NewClient creates a new GitHub client
func NewClient() *Client {
	return &Client{
		Owner: DefaultOwner,
		Repo:  DefaultRepo,
	}
}

// CheckAuth verifies that gh CLI is authenticated
func (c *Client) CheckAuth() error {
	cmd := exec.Command("gh", "auth", "status")
	output, err := cmd.CombinedOutput()
	if err != nil {
		return fmt.Errorf("GitHub CLI not authenticated. Run 'gh auth login' first.\n%s", string(output))
	}
	return nil
}

// ghAPI executes a gh api command and returns the output
func (c *Client) ghAPI(method, endpoint string, body ...string) ([]byte, error) {
	args := []string{"api", "-X", method, endpoint}
	if len(body) > 0 && body[0] != "" {
		args = append(args, "-f", body[0])
	}
	cmd := exec.Command("gh", args...)
	output, err := cmd.CombinedOutput()
	if err != nil {
		return nil, fmt.Errorf("gh api error: %s\n%s", err, string(output))
	}
	return output, nil
}

// FileContent represents a file from the GitHub API
type FileContent struct {
	Name        string `json:"name"`
	Path        string `json:"path"`
	SHA         string `json:"sha"`
	Content     string `json:"content"`
	Encoding    string `json:"encoding"`
	DownloadURL string `json:"download_url"`
}

// FetchManifest retrieves the manifest.yaml from GitHub
func (c *Client) FetchManifest() (*models.Manifest, error) {
	endpoint := fmt.Sprintf("/repos/%s/%s/contents/manifest.yaml", c.Owner, c.Repo)
	output, err := c.ghAPI("GET", endpoint)
	if err != nil {
		return nil, err
	}

	var fc FileContent
	if err := json.Unmarshal(output, &fc); err != nil {
		return nil, fmt.Errorf("failed to parse response: %w", err)
	}

	content, err := base64.StdEncoding.DecodeString(strings.ReplaceAll(fc.Content, "\n", ""))
	if err != nil {
		return nil, fmt.Errorf("failed to decode content: %w", err)
	}

	var manifest models.Manifest
	if err := yaml.Unmarshal(content, &manifest); err != nil {
		return nil, fmt.Errorf("failed to parse manifest: %w", err)
	}

	return &manifest, nil
}

// FetchDeviceFile retrieves a device YAML file from GitHub
func (c *Client) FetchDeviceFile(path string) (*models.DeviceFile, string, error) {
	endpoint := fmt.Sprintf("/repos/%s/%s/contents/%s", c.Owner, c.Repo, path)
	output, err := c.ghAPI("GET", endpoint)
	if err != nil {
		return nil, "", err
	}

	var fc FileContent
	if err := json.Unmarshal(output, &fc); err != nil {
		return nil, "", fmt.Errorf("failed to parse response: %w", err)
	}

	content, err := base64.StdEncoding.DecodeString(strings.ReplaceAll(fc.Content, "\n", ""))
	if err != nil {
		return nil, "", fmt.Errorf("failed to decode content: %w", err)
	}

	var deviceFile models.DeviceFile
	if err := yaml.Unmarshal(content, &deviceFile); err != nil {
		return nil, "", fmt.Errorf("failed to parse device file: %w", err)
	}

	return &deviceFile, fc.SHA, nil
}

// BranchInfo represents branch information
type BranchInfo struct {
	Name   string `json:"name"`
	Commit struct {
		SHA string `json:"sha"`
	} `json:"commit"`
}

// CreateBranch creates a new branch from main
func (c *Client) CreateBranch(branchName string) error {
	// Get main branch SHA
	endpoint := fmt.Sprintf("/repos/%s/%s/branches/main", c.Owner, c.Repo)
	output, err := c.ghAPI("GET", endpoint)
	if err != nil {
		return fmt.Errorf("failed to get main branch: %w", err)
	}

	var branch BranchInfo
	if err := json.Unmarshal(output, &branch); err != nil {
		return fmt.Errorf("failed to parse branch info: %w", err)
	}

	// Create new branch
	createEndpoint := fmt.Sprintf("/repos/%s/%s/git/refs", c.Owner, c.Repo)
	cmd := exec.Command("gh", "api", "-X", "POST", createEndpoint,
		"-f", fmt.Sprintf("ref=refs/heads/%s", branchName),
		"-f", fmt.Sprintf("sha=%s", branch.Commit.SHA))

	output, err = cmd.CombinedOutput()
	if err != nil {
		return fmt.Errorf("failed to create branch: %s", string(output))
	}

	return nil
}

// UpdateFile updates a file on a branch
func (c *Client) UpdateFile(path, content, sha, branch, message string) error {
	encoded := base64.StdEncoding.EncodeToString([]byte(content))
	endpoint := fmt.Sprintf("/repos/%s/%s/contents/%s", c.Owner, c.Repo, path)

	cmd := exec.Command("gh", "api", "-X", "PUT", endpoint,
		"-f", fmt.Sprintf("message=%s", message),
		"-f", fmt.Sprintf("content=%s", encoded),
		"-f", fmt.Sprintf("sha=%s", sha),
		"-f", fmt.Sprintf("branch=%s", branch))

	output, err := cmd.CombinedOutput()
	if err != nil {
		return fmt.Errorf("failed to update file: %s", string(output))
	}

	return nil
}

// PRResponse from creating a PR
type PRResponse struct {
	Number  int    `json:"number"`
	HTMLURL string `json:"html_url"`
}

// CreatePR creates a pull request
func (c *Client) CreatePR(title, body, branch string) (*PRResponse, error) {
	cmd := exec.Command("gh", "pr", "create",
		"--repo", fmt.Sprintf("%s/%s", c.Owner, c.Repo),
		"--title", title,
		"--body", body,
		"--head", branch,
		"--base", "main")

	output, err := cmd.CombinedOutput()
	if err != nil {
		return nil, fmt.Errorf("failed to create PR: %s", string(output))
	}

	// Parse the PR URL from output
	url := strings.TrimSpace(string(output))
	return &PRResponse{HTMLURL: url}, nil
}

// GetCurrentUser returns the authenticated user's login
func (c *Client) GetCurrentUser() (string, error) {
	cmd := exec.Command("gh", "api", "/user", "-q", ".login")
	output, err := cmd.CombinedOutput()
	if err != nil {
		return "", fmt.Errorf("failed to get user: %s", string(output))
	}
	return strings.TrimSpace(string(output)), nil
}

// CanWrite returns true - GitHub source can create PRs
func (c *Client) CanWrite() bool {
	return true
}

// CreatePRFromChanges implements the Source interface for creating PRs
func (c *Client) CreatePRFromChanges(title, body string, files map[string]source.FileChange) (string, error) {
	// Create branch name
	branchName := fmt.Sprintf("sparkctl-update-%d", time.Now().Unix())

	// Create branch
	if err := c.CreateBranch(branchName); err != nil {
		return "", fmt.Errorf("failed to create branch: %w", err)
	}

	// Update each changed file
	for path, change := range files {
		if err := c.UpdateFile(path, change.Content, change.SHA, branchName, "Update device definitions"); err != nil {
			return "", fmt.Errorf("failed to update %s: %w", path, err)
		}
	}

	// Create PR
	pr, err := c.CreatePR(title, body, branchName)
	if err != nil {
		return "", err
	}

	return pr.HTMLURL, nil
}
