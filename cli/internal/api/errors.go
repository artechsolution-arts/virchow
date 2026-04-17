package api

import "fmt"

// VirchowAPIError is returned when an Virchow API call fails.
type VirchowAPIError struct {
	StatusCode int
	Detail     string
}

func (e *VirchowAPIError) Error() string {
	return fmt.Sprintf("HTTP %d: %s", e.StatusCode, e.Detail)
}
