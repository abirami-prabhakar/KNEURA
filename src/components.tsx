import type { ReactNode } from 'react'

export function Icon({ name, size = 18 }: { name: string; size?: number }) {
  const paths: Record<string, ReactNode> = {
    grid: <><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></>,
    folder: <path d="M3 7V5a1 1 0 0 1 1-1h6l2 3h8a1 1 0 0 1 1 1v11a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V7Z"/>,
    scan: <><path d="M8 3H3v5m13-5h5v5M3 16v5h5m13-5v5h-5M7 12h10"/><path d="m10 9-3 3 3 3m4-6 3 3-3 3"/></>,
    report: <><path d="M14 3H5v18h14V8l-5-5Z"/><path d="M14 3v5h5M8 12h8m-8 4h6"/></>,
    clock: <><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></>,
    model: <><path d="m12 3 9 5v8l-9 5-9-5V8l9-5Zm0 0v18M3 8l9 5 9-5"/></>,
    chart: <><path d="M4 3v17h17M8 15v-4m5 4V6m5 9V9"/></>,
    arrow: <path d="M4 12h15m-5-5 5 5-5 5"/>,
    plus: <path d="M12 5v14M5 12h14"/>,
    search: <><circle cx="10" cy="10" r="6"/><path d="m15 15 5 5"/></>,
    chevron: <path d="m9 5 7 7-7 7"/>,
    down: <path d="m6 9 6 6 6-6"/>,
    check: <path d="m5 12 4 4L19 6"/>,
    close: <path d="m6 6 12 12M6 18 18 6"/>,
    upload: <><path d="M12 16V3m-5 5 5-5 5 5M4 15v6h16v-6"/></>,
    shield: <><path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6l8-3Z"/><path d="m8 12 3 3 5-6"/></>,
    help: <><circle cx="12" cy="12" r="9"/><path d="M9 9a3 3 0 1 1 4 3v2m-1 3h.01"/></>,
    settings: <><path d="M4 7h16M4 17h16"/><circle cx="9" cy="7" r="3"/><circle cx="16" cy="17" r="3"/></>,
    exit: <><path d="M10 4H4v16h6m3-13 5 5-5 5m-5-5h12"/></>,
    expand: <path d="M9 3H3v6m12-6h6v6M3 15v6h6m12-6v6h-6"/>,
  }
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name] || paths.folder}</svg>
}
export function Brand() { return <div className="brand"><span className="brand-symbol"><i/><i/><i/></span>KNEURA<span className="brand-period">.</span></div> }
export function StatusBadge({ status }: { status: string }) { return <span className={`status status-${status.toLowerCase()}`}><span/>{status.replaceAll('_', ' ')}</span> }
export function EmptyState({ icon = 'folder', title, description, action }: { icon?: string; title: string; description: string; action?: ReactNode }) { return <div className="empty-state"><span className="empty-icon"><Icon name={icon} size={25}/></span><h3>{title}</h3><p>{description}</p>{action}</div> }
export function ErrorState({ message, retry }: { message: string; retry?: () => void }) { return <div className="error-state" role="alert"><Icon name="help"/><span>{message}</span>{retry && <button className="text-button" onClick={retry}>Try again <Icon name="arrow" size={14}/></button>}</div> }
export function LoadingState() { return <div className="loading-state" role="status"><span/><span/><span/><p>Loading workspace</p></div> }
export function Workflow({ compact = false }: { compact?: boolean }) { return <div className={`workflow ${compact ? 'compact' : ''}`}>{[['scan','AI proposes','12 canonical findings'], ['scan','Evidence supports','MRI + Grad-CAM'], ['shield','You verify','Approve or reject'], ['report','Report follows','Approved findings only']].map(([icon,title,sub],i)=><div className="workflow-step" key={title}><div className="workflow-top"><span className="step-number">0{i+1}</span><Icon name={icon}/></div><strong>{title}</strong><small>{sub}</small>{i<3 && <span className="step-arrow">↗</span>}</div>)}</div> }
