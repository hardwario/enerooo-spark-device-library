package tui

import "github.com/charmbracelet/lipgloss"

// Color palette
var (
	// Primary colors
	primaryColor   = lipgloss.Color("#7C3AED") // Purple
	secondaryColor = lipgloss.Color("#10B981") // Green
	accentColor    = lipgloss.Color("#F59E0B") // Amber
	errorColor     = lipgloss.Color("#EF4444") // Red
	mutedColor     = lipgloss.Color("#6B7280") // Gray
	dimColor       = lipgloss.Color("#374151") // Dark gray

	// Background colors
	bgColor        = lipgloss.Color("#1F2937") // Dark bg
	bgLightColor   = lipgloss.Color("#374151") // Slightly lighter
	bgSelectedColor = lipgloss.Color("#4C1D95") // Purple bg for selection

	// Text colors
	textColor      = lipgloss.Color("#F9FAFB") // White
	textMutedColor = lipgloss.Color("#9CA3AF") // Light gray
)

// Layout dimensions
const (
	minWidth = 70
)

// Header styles
var (
	logoStyle = lipgloss.NewStyle().
		Bold(true).
		Foreground(primaryColor)

	headerStyle = lipgloss.NewStyle().
		BorderStyle(lipgloss.RoundedBorder()).
		BorderForeground(dimColor).
		Padding(0, 1)

	breadcrumbStyle = lipgloss.NewStyle().
		Foreground(textMutedColor)

	breadcrumbActiveStyle = lipgloss.NewStyle().
		Foreground(textColor).
		Bold(true)

	modeLocalStyle = lipgloss.NewStyle().
		Background(secondaryColor).
		Foreground(lipgloss.Color("#000000")).
		Padding(0, 1).
		Bold(true)

	modeGitHubStyle = lipgloss.NewStyle().
		Background(primaryColor).
		Foreground(lipgloss.Color("#FFFFFF")).
		Padding(0, 1).
		Bold(true)
)

// Content panel styles
var (
	panelStyle = lipgloss.NewStyle().
		BorderStyle(lipgloss.RoundedBorder()).
		BorderForeground(dimColor).
		Padding(1, 2)

	panelTitleStyle = lipgloss.NewStyle().
		Bold(true).
		Foreground(textColor).
		MarginBottom(1)

	panelSubtitleStyle = lipgloss.NewStyle().
		Foreground(textMutedColor).
		MarginBottom(1)
)

// List styles
var (
	listItemStyle = lipgloss.NewStyle().
		PaddingLeft(2).
		Foreground(textColor)

	listItemSelectedStyle = lipgloss.NewStyle().
		Background(bgSelectedColor).
		Foreground(textColor).
		Bold(true).
		PaddingLeft(1).
		PaddingRight(1)

	listItemDimStyle = lipgloss.NewStyle().
		PaddingLeft(2).
		Foreground(textMutedColor)
)

// Badge styles
var (
	badgeModifiedStyle = lipgloss.NewStyle().
		Background(accentColor).
		Foreground(lipgloss.Color("#000000")).
		Padding(0, 1).
		Bold(true)

	badgeTechStyle = lipgloss.NewStyle().
		Background(dimColor).
		Foreground(textColor).
		Padding(0, 1)

	badgeControllableStyle = lipgloss.NewStyle().
		Foreground(secondaryColor)

	badgeDeviceTypeStyle = lipgloss.NewStyle().
		Foreground(textMutedColor).
		Italic(true)
)

// Form/Edit styles
var (
	labelStyle = lipgloss.NewStyle().
		Foreground(textMutedColor).
		Width(18)

	valueStyle = lipgloss.NewStyle().
		Foreground(textColor)

	valueEditableStyle = lipgloss.NewStyle().
		Foreground(secondaryColor)

	inputStyle = lipgloss.NewStyle().
		Border(lipgloss.RoundedBorder()).
		BorderForeground(primaryColor).
		Padding(0, 1)

	inputFocusedStyle = lipgloss.NewStyle().
		Border(lipgloss.RoundedBorder()).
		BorderForeground(accentColor).
		Padding(0, 1)
)

// Footer/Status bar styles
var (
	footerStyle = lipgloss.NewStyle().
		BorderStyle(lipgloss.RoundedBorder()).
		BorderForeground(dimColor).
		Padding(0, 1)

	helpKeyStyle = lipgloss.NewStyle().
		Foreground(textMutedColor)

	helpDescStyle = lipgloss.NewStyle().
		Foreground(primaryColor)

	statusStyle = lipgloss.NewStyle().
		Foreground(textMutedColor)

	changesCountStyle = lipgloss.NewStyle().
		Foreground(accentColor).
		Bold(true)
)

// Error/Message styles
var (
	errorStyle = lipgloss.NewStyle().
		Foreground(errorColor).
		Bold(true)

	successStyle = lipgloss.NewStyle().
		Foreground(secondaryColor).
		Bold(true)

	boxStyle = lipgloss.NewStyle().
		Border(lipgloss.RoundedBorder()).
		BorderForeground(primaryColor).
		Padding(1, 2)
)

// Icons
const (
	IconSelected     = "▸"
	IconUnselected   = " "
	IconControllable = "✓"
	IconModified     = "●"
	IconFolder       = "📁"
	IconDevice       = "⚡"
	IconArrowRight   = "›"
	IconSpinner      = "◐"
)

// Device type icons
func deviceTypeIcon(deviceType string) string {
	switch deviceType {
	case "power_meter":
		return "⚡"
	case "gateway":
		return "🌐"
	case "environment_sensor":
		return "🌡"
	case "water_meter":
		return "💧"
	case "heat_meter":
		return "🔥"
	default:
		return "📦"
	}
}

// Technology badge color
func techBadgeStyle(tech string) lipgloss.Style {
	switch tech {
	case "lorawan":
		return badgeTechStyle.Background(lipgloss.Color("#3B82F6")) // Blue
	case "modbus":
		return badgeTechStyle.Background(lipgloss.Color("#8B5CF6")) // Purple
	case "wmbus":
		return badgeTechStyle.Background(lipgloss.Color("#EC4899")) // Pink
	default:
		return badgeTechStyle
	}
}
