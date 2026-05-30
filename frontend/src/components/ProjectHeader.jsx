import { useParams } from "react-router-dom";
import { useFetch } from "../hooks/useFetch";
import { api } from "../services/api";
import { Badge } from "./ui";
import { CaptureButton, ReprocessButton } from "./CaptureButton";

export function ProjectHeader({ onAction }) {
  const { projectId } = useParams();
  const { data: project } = useFetch(() => api.getProject(projectId), [projectId]);
  if (!project) return null;
  return (
    <div className="flex items-center justify-between mb-8">
      <div>
        <div className="text-xs uppercase tracking-wider text-text-muted">Project</div>
        <h1 className="text-2xl font-semibold">{project.name}</h1>
        <div className="flex items-center gap-2 mt-1 flex-wrap">
          <span className="text-sm font-mono text-text-muted">{project.domain}</span>
          {project.geo_location && <Badge>{project.geo_location}</Badge>}
          <Badge tone="info">{project.prompts.length} prompts</Badge>
          <Badge>{project.competitors.length} competitors</Badge>
          <Badge>{(project.providers || []).length} providers</Badge>
        </div>
      </div>
      <div className="flex items-center gap-2">
        <ReprocessButton projectId={projectId} onDone={onAction} />
        <CaptureButton
          projectId={projectId}
          onStarted={onAction}
          initialProviders={project.providers}
        />
      </div>
    </div>
  );
}
