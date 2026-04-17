package cmd

import (
	tea "github.com/charmbracelet/bubbletea"
	"github.com/virchow-dot-app/virchow/cli/internal/config"
	"github.com/virchow-dot-app/virchow/cli/internal/onboarding"
	"github.com/virchow-dot-app/virchow/cli/internal/tui"
	"github.com/spf13/cobra"
)

func newChatCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "chat",
		Short: "Launch the interactive chat TUI (default)",
		RunE: func(cmd *cobra.Command, args []string) error {
			cfg := config.Load()

			// First-run: onboarding
			if !config.ConfigExists() || !cfg.IsConfigured() {
				result := onboarding.Run(&cfg)
				if result == nil {
					return nil
				}
				cfg = *result
			}

			m := tui.NewModel(cfg)
			p := tea.NewProgram(m, tea.WithAltScreen(), tea.WithMouseCellMotion())
			_, err := p.Run()
			return err
		},
	}
}
