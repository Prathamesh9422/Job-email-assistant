import { defineRailway, github, postgres, project, service, volume } from "railway/iac";

export default defineRailway(() => {
  const JobEmailAssistant = github("Prathamesh9422/Job-email-assistant");

  const Postgres = postgres("Postgres", { region: "sfo" });

  const dashboardData = volume("dashboard-data", { region: "sfo", sizeMB: 500 });

  const fetchCron = service("fetch-cron", {
    source: JobEmailAssistant,
    startCommand: "python fetch_job.py",
    deploy: { cronSchedule: "30 14 * * *" },
    replicas: { sfo: 1 },
    variables: {
      DATABASE_URL: Postgres.env.DATABASE_URL,
    },
  });

  const dashboard = service("dashboard", {
    source: JobEmailAssistant,
    startCommand: "uvicorn app:app --host 0.0.0.0 --port $PORT",
    replicas: { sfo: 1 },
    volumeMounts: { "/data": dashboardData },
    variables: {
      DATABASE_URL: Postgres.env.DATABASE_URL,
      DATA_DIR: "/data",
    },
  });

  return project("job-email-assistant", {
    resources: [Postgres, fetchCron, dashboard, dashboardData],
  });
});
