export type ReportShareType =
  | 'attribution'
  | 'qualified_leads'
  | 'monthly_consolidated'
  | 'marketing_ramp'
  | 'web_leads';

export function buildReportShareUrl(
  jobId: string,
  reportType?: ReportShareType,
  origin?: string
): string {
  const base = origin ?? window.location.origin;
  const url = new URL(window.location.pathname, base);
  url.searchParams.set('report', jobId);
  if (reportType && reportType !== 'attribution') {
    url.searchParams.set('type', reportType);
  }
  return url.toString();
}

export async function copyReportShareUrl(
  jobId: string,
  reportType?: ReportShareType
): Promise<'copied' | 'prompt'> {
  const reportUrl = buildReportShareUrl(jobId, reportType);
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(reportUrl);
      return 'copied';
    }
    window.prompt('Copy this report link:', reportUrl);
    return 'prompt';
  } catch {
    window.prompt('Copy this report link:', reportUrl);
    return 'prompt';
  }
}
