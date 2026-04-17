package cmd

import (
	"github.com/virchow-dot-app/virchow/cli/internal/config"
	"github.com/virchow-dot-app/virchow/cli/internal/onboarding"
	"github.com/spf13/cobra"
)

func newConfigureCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "configure",
		Short: "Configure server URL and API key",
		RunE: func(cmd *cobra.Command, args []string) error {
			cfg := config.Load()
			onboarding.Run(&cfg)
			return nil
		},
	}
}
