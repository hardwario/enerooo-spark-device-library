package main

import (
	"flag"
	"fmt"
	"os"
	"os/exec"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/hardwario/enerooo-spark-device-library/tools/sparkctl/internal/tui"
)

func main() {
	// Parse flags
	localMode := flag.Bool("local", false, "Read from local filesystem instead of GitHub")
	localPath := flag.String("path", ".", "Path to local repository (used with -local)")
	flag.Parse()

	// Only check GitHub auth if not in local mode
	if !*localMode {
		// Check for gh CLI
		if _, err := exec.LookPath("gh"); err != nil {
			fmt.Fprintln(os.Stderr, "Error: GitHub CLI (gh) is required but not installed.")
			fmt.Fprintln(os.Stderr, "Install it from: https://cli.github.com/")
			fmt.Fprintln(os.Stderr, "\nOr use -local flag to read from local filesystem.")
			os.Exit(1)
		}

		// Check gh auth status
		cmd := exec.Command("gh", "auth", "status")
		if err := cmd.Run(); err != nil {
			fmt.Fprintln(os.Stderr, "Error: Not authenticated with GitHub CLI.")
			fmt.Fprintln(os.Stderr, "Run 'gh auth login' to authenticate.")
			fmt.Fprintln(os.Stderr, "\nOr use -local flag to read from local filesystem.")
			os.Exit(1)
		}
	}

	// Run the TUI
	p := tea.NewProgram(
		tui.NewModel(*localMode, *localPath),
		tea.WithAltScreen(),
	)

	if _, err := p.Run(); err != nil {
		fmt.Fprintf(os.Stderr, "Error: %v\n", err)
		os.Exit(1)
	}
}
