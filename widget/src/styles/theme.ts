import { css } from "lit";
import { colors } from "./colors";

/**
 * Virchow Design System - Theme
 * Typography, spacing, and layout tokens from Figma
 */
export const theme = css`
  ${colors}

  :host {
    /* Typography - Hanken Grotesk */
    --virchow-font-family: "Hanken Grotesk", -apple-system, BlinkMacSystemFont,
      "Segoe UI", sans-serif;
    --virchow-font-family-mono: "DM Mono", "Monaco", "Menlo", monospace;

    /* Font Sizes */
    --virchow-font-size-small: 10px;
    --virchow-font-size-secondary: 12px;
    --virchow-font-size-sm: 13px;
    --virchow-font-size-main: 14px;
    --virchow-font-size-label: 16px;

    /* Line Heights */
    --virchow-line-height-small: 12px;
    --virchow-line-height-secondary: 16px;
    --virchow-line-height-main: 20px;
    --virchow-line-height-label: 24px;
    --virchow-line-height-section: 28px;
    --virchow-line-height-headline: 36px;

    /* Font Weights */
    --virchow-weight-regular: 400;
    --virchow-weight-medium: 500;
    --virchow-weight-semibold: 600;

    /* Content Heights */
    --virchow-height-content-secondary: 12px;
    --virchow-height-content-main: 16px;
    --virchow-height-content-label: 18px;
    --virchow-height-content-section: 24px;

    /* Border Radius - from Figma */
    --virchow-radius-04: 4px;
    --virchow-radius-08: 8px;
    --virchow-radius-12: 12px;
    --virchow-radius-16: 16px;
    --virchow-radius-round: 1000px;

    /* Spacing - Block */
    --virchow-space-block-1x: 4px;
    --virchow-space-block-2x: 8px;
    --virchow-space-block-3x: 12px;
    --virchow-space-block-4x: 16px;
    --virchow-space-block-6x: 24px;

    /* Spacing - Inline */
    --virchow-space-inline-0: 0px;
    --virchow-space-inline-0_5x: 2px;
    --virchow-space-inline-1x: 4px;

    /* Legacy spacing aliases (for compatibility) */
    --virchow-space-2xs: var(--virchow-space-block-1x);
    --virchow-space-xs: var(--virchow-space-block-2x);
    --virchow-space-sm: var(--virchow-space-block-3x);
    --virchow-space-md: var(--virchow-space-block-4x);
    --virchow-space-lg: var(--virchow-space-block-6x);

    /* Padding */
    --virchow-padding-icon-0: 0px;
    --virchow-padding-icon-0_5x: 2px;
    --virchow-padding-text-0_5x: 2px;
    --virchow-padding-text-1x: 4px;

    /* Icon Weights (stroke-width) */
    --virchow-icon-weight-secondary: 1px;
    --virchow-icon-weight-main: 1.5px;
    --virchow-icon-weight-section: 2px;

    /* Z-index */
    --virchow-z-launcher: 9999;
    --virchow-z-widget: 10000;

    /* Transitions */
    --virchow-transition-fast: 150ms cubic-bezier(0.4, 0, 0.2, 1);
    --virchow-transition-base: 200ms cubic-bezier(0.4, 0, 0.2, 1);
  }

  * {
    box-sizing: border-box;
  }
`;
