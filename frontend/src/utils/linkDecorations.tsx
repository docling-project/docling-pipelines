/**
 * @file linkDecorations.tsx
 *
 * Shared utility for applying link-name pill decorations to Branching and
 * Merging links on an Elyra canvas controller.
 *
 * Used by both the edit canvas (Canvas.tsx) and the read-only run canvas
 * (ReadOnlyCanvas.tsx) so that link capsules are visible in both views.
 */

import type { CanvasController } from '@elyra/canvas';
import { AddFilled } from '@carbon/icons-react';
import { NodeOperator } from '@/constants/operators';
import { CANVAS_ACTIONS } from '@/constants/canvasActions';
import styles from './linkDecorations.module.scss';

// ---------------------------------------------------------------------------
// Decoration builder
// ---------------------------------------------------------------------------

/**
 * Builds the decoration array for a canvas link.
 *
 * - Named link  → clickable pill showing the link name.
 * - Unnamed link → `Add` icon inviting the user to add a condition.
 *   (In read-only mode the `Add` icon is still rendered but the hotspot click
 *   will not open a tearsheet because no `decorationActionHandler` is wired up.)
 *
 * @param label  The link name string (empty string = no name set).
 * @param linkId The Elyra link UUID — used to build stable decoration ids.
 * @param readOnly When true, suppress the Add icon (no editing possible).
 */
export function buildLinkDecorations(
  label: string,
  linkId: string,
  readOnly = false
): object[] {
  if (label) {
    return [
      {
        id: `${linkId}-pill`,
        x_pos: -50,
        y_pos: 0,
        position: 'middle',
        height: 32,
        width: 120,
        jsx: (
          <div className={`${styles.linkPill}${readOnly ? ` ${styles.linkPillReadOnly}` : ''}`}>
            {label}
          </div>
        ),
        hotspot: !readOnly,
        outline: false,
      },
    ];
  }

  // In read-only mode do not render the "add condition" affordance.
  if (readOnly) { return []; }

  return [
    {
      id: `${linkId}-${CANVAS_ACTIONS.ADD_CONDITION}`,
      height: 16,
      width: 16,
      x_pos: -8,
      y_pos: -8,
      jsx: (
        <AddFilled
          aria-label="Add condition"
          className={styles.addConditionIcon}
        />
      ),
      hotspot: true,
      outline: false,
      position: 'middle',
    },
  ];
}

// ---------------------------------------------------------------------------
// Bulk applicator
// ---------------------------------------------------------------------------

/**
 * Iterates every node in the pipeline flow and stamps link-name pill
 * decorations onto all Branching-node output links and Merging-node input links.
 *
 * Safe to call multiple times — each call overwrites the previous decorations.
 *
 * @param controller  Live Elyra `CanvasController` instance.
 * @param readOnly    When true, pill is non-clickable and unnamed links get no
 *                    decoration (no Add icon affordance in run-view).
 */
type PipelineNode = Record<string, unknown>;
type PipelineLink = Record<string, unknown>;
type PipelineInput = { links?: PipelineLink[] };

export function applyAllLinkDecorations(
  controller: CanvasController,
  readOnly = false
): void {
  const flow = controller.getPipelineFlow() as unknown as { pipelines?: Array<{ nodes?: PipelineNode[] }> } | undefined;
  const nodes: PipelineNode[] = flow?.pipelines?.[0]?.nodes ?? [];

  const branchingNodeIds = new Set(
    nodes.filter((n) => n['op'] === NodeOperator.BRANCHING).map((n) => n['id'] as string)
  );

  nodes.forEach((node) => {
    // ── Outgoing links from Branching nodes ──
    const inputs = (node['inputs'] as PipelineInput[] | undefined) ?? [];
    inputs.forEach((input) => {
      (input.links ?? []).forEach((link) => {
        if (branchingNodeIds.has(link['node_id_ref'] as string)) {
          const branchingNode = nodes.find((n) => n['id'] === link['node_id_ref']);
          const params        = branchingNode?.['parameters'] as Record<string, unknown> | undefined;
          const linkConditions = (params?.['link_conditions'] as PipelineLink[] | undefined) ?? [];
          const condition = linkConditions.find((lc) => lc['link_id'] === link['id']);
          const label: string = (condition?.['link_name'] as string | undefined) ?? '';

          controller.setLinkDecorations(link['id'] as string, buildLinkDecorations(label, link['id'] as string, readOnly) as never);
        }
      });
    });

    // ── Incoming links to Merging nodes ──
    if (node['op'] === NodeOperator.MERGING) {
      const mergeInputs = (node['inputs'] as PipelineInput[] | undefined) ?? [];
      mergeInputs.forEach((input) => {
        (input.links ?? []).forEach((link) => {
          const label: string = (link['link_name'] as string | undefined) ?? '';

          controller.setLinkDecorations(link['id'] as string, buildLinkDecorations(label, link['id'] as string, readOnly) as never);
        });
      });
    }
  });
}
