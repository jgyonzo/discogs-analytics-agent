// Result panel: chart on top, then run metadata badges, then a tabular
// data preview, then the collapsible SQL viewer at the bottom.
// Each child component handles its own null/empty case so this layout
// stays declarative.

import { ArtifactFrame } from "./ArtifactFrame";
import { DataPreviewTable } from "./DataPreviewTable";
import { RunMetadata } from "./RunMetadata";
import { SqlViewer } from "./SqlViewer";
import type { AppState } from "../api/types";

export type ResultPanelProps = {
  current: AppState["current"];
};

export function ResultPanel({ current }: ResultPanelProps) {
  return (
    <div className="flex flex-col gap-3">
      <ArtifactFrame artifact={current.artifact} />
      <RunMetadata metadata={current.metadata} />
      {current.dataframePreview.length > 0 && (
        <DataPreviewTable rows={current.dataframePreview} />
      )}
      <SqlViewer sql={current.sql} />
    </div>
  );
}
