interface DashboardLoaderProps {
  title?: string;
  description?: string;
}

export default function DashboardLoader({
  title = 'Loading',
  description = 'Please wait...',
}: DashboardLoaderProps) {
  return (
    <div className="dashboard-loader">
      <div className="dashboard-loader-spinner" />
      <h3 className="dashboard-loader-title">{title}</h3>
      <p className="dashboard-loader-desc">{description}</p>
    </div>
  );
}
