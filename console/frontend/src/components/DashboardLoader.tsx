interface DashboardLoaderProps {
  title?: string;
  description?: string;
  compact?: boolean;
}

export default function DashboardLoader({
  title = 'Loading',
  description = 'Please wait...',
  compact = false,
}: DashboardLoaderProps) {
  return (
    <div
      className={`dashboard-loader ${compact ? 'dashboard-loader-compact' : ''}`}
      aria-live="polite"
      aria-busy="true"
    >
      <div className="dashboard-loader-visual" aria-hidden="true">
        <div className="dashboard-loader-video-frame">
          <video
            className="dashboard-loader-video"
            autoPlay
            loop
            muted
            playsInline
            preload="auto"
          >
            <source src="/load_animation.mp4" type="video/mp4" />
          </video>
        </div>
      </div>
      <div className="dashboard-loader-copy">
        <h3>{title}</h3>
        <p>{description}</p>
      </div>
    </div>
  );
}
