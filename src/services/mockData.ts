import type {
  ActivityEvent,
  AgentConfig,
  AgentTask,
  AuditEntry,
  Company,
  Department,
  DepartmentExchange,
  Insight,
  KnowledgeStatus,
  LibraryItem,
  MailMessage,
  RecentItem,
  RoleDefinition,
  Schedule,
  SessionUser,
} from "./types";

export const companies: Company[] = [
  {
    id: "nexora",
    name: "NEXORA SYSTEMS",
    industry: "Industrial Software",
    region: "EMEA · 4 sites",
    employees: 1840,
    agentRole: "Data Intelligence Agent",
    agentName: "NX-1 Data Intelligence Agent",
  },
  {
    id: "acme",
    name: "ACME TECHNOLOGIES",
    industry: "Hardware Manufacturing",
    region: "APAC · 2 sites",
    employees: 620,
    agentRole: "Operations Analyst Agent",
    agentName: "AC-2 Operations Analyst Agent",
  },
  {
    id: "halden",
    name: "HALDEN CAPITAL",
    industry: "Financial Services",
    region: "NA · 1 site",
    employees: 210,
    agentRole: "Financial Reporting Agent",
    agentName: "HC-3 Financial Reporting Agent",
  },
];

export const departments: Department[] = [
  { key: "sales", name: "Sales", systems: ["CRM", "Pipeline DB"], linkStrength: 0.92 },
  { key: "finance", name: "Finance", systems: ["ERP", "Ledger"], linkStrength: 0.74 },
  {
    key: "customer_service",
    name: "Customer Service",
    systems: ["Ticketing", "CSAT"],
    linkStrength: 0.81,
  },
  { key: "operations", name: "Operations", systems: ["MES", "Logistics"], linkStrength: 0.44 },
  { key: "marketing", name: "Marketing", systems: ["Campaigns", "Web analytics"], linkStrength: 0.31 },
  { key: "hr", name: "HR", systems: ["HRIS", "Rota"], linkStrength: 0.18 },
  { key: "it", name: "IT", systems: ["Service desk", "Access"], linkStrength: 0.26 },
  { key: "design", name: "Design", systems: ["Asset library"], linkStrength: 0.12 },
];

export const departmentName = (k: string) =>
  departments.find((d) => d.key === k)?.name ?? k;

export const sessionUserSeed: Omit<SessionUser, "companyId" | "role"> = {
  id: "u-1",
  name: "Elena Marsh",
  email: "elena.marsh@nexora.io",
  status: "Active",
};

export const activityFeed: ActivityEvent[] = [
  { id: "a1", time: "10:42", text: "Detected unusual sales variation in Region A", kind: "detect", department: "sales" },
  { id: "a2", time: "10:43", text: "Analyzing 18 months of regional sales records", kind: "analyze", department: "sales" },
  { id: "a3", time: "10:44", text: "Consulting Customer Service complaint trends", kind: "consult", department: "customer_service" },
  { id: "a4", time: "10:46", text: "Root cause identified — fulfilment delay correlation", kind: "result", department: "operations" },
  { id: "a5", time: "10:47", text: "Performance report prepared for management", kind: "execute" },
  { id: "a6", time: "10:48", text: "Waiting for approval to distribute report", kind: "await" },
];

export const streamCandidates: Omit<ActivityEvent, "id" | "time">[] = [
  { text: "Reconciling Finance ledger export with CRM revenue", kind: "consult", department: "finance" },
  { text: "Indexing 12 new documents into knowledge base", kind: "execute" },
  { text: "Monitoring pipeline velocity — no anomalies", kind: "detect", department: "sales" },
  { text: "Retention model refreshed with Q3 churn data", kind: "analyze", department: "customer_service" },
  { text: "Requested clarification from Operations on delivery SLA", kind: "consult", department: "operations" },
  { text: "Draft executive summary generated", kind: "result" },
];

export const tasks: AgentTask[] = [
  {
    id: "t1",
    name: "Sales Performance Analysis",
    goal: "Analyze the current sales decline across regions and identify root cause.",
    status: "awaiting_approval",
    progress: 82,
    startedAt: "10:42",
    department: "sales",
    requiredAction: "Approve report distribution",
    steps: [
      { label: "Understand goal", detail: "Scope set to Region A, trailing 6 months", state: "done" },
      { label: "Collect sales data", detail: "Retrieved 42,180 order records via approved Sales Analytics tool", state: "done" },
      { label: "Analyze trends", detail: "Detected -18.4% variance vs. forecast", state: "done" },
      { label: "Consult Customer Service", detail: "Compared complaint volume trend (+23%)", state: "done" },
      { label: "Compare finance data", detail: "Matched revenue recognition against ledger", state: "done" },
      { label: "Identify cause", detail: "Fulfilment delays in two distribution hubs", state: "done" },
      { label: "Generate report", detail: "Performance report v1 prepared", state: "active" },
      { label: "Recommendation", detail: "Pending human approval before distribution", state: "pending" },
    ],
    sources: ["Company Sales Policy.pdf", "Q2 Revenue Report.xlsx", "Customer Service SOP.pdf"],
  },
  {
    id: "t2",
    name: "Customer Trend Report",
    goal: "Summarize customer sentiment and complaint categories for the quarter.",
    status: "running",
    progress: 54,
    startedAt: "09:15",
    department: "customer_service",
    steps: [
      { label: "Understand goal", detail: "Quarterly sentiment breakdown requested", state: "done" },
      { label: "Collect tickets", detail: "6,204 tickets ingested", state: "done" },
      { label: "Classify categories", detail: "Clustering in progress", state: "active" },
      { label: "Generate report", detail: "Not started", state: "pending" },
    ],
    sources: ["Customer Service SOP.pdf", "CSAT_Q3.csv"],
  },
  {
    id: "t3",
    name: "Monthly Revenue Analysis",
    goal: "Close the monthly revenue picture and flag anomalies.",
    status: "completed",
    progress: 100,
    startedAt: "Yesterday 18:00",
    department: "finance",
    steps: [
      { label: "Understand goal", detail: "Month-end revenue close", state: "done" },
      { label: "Collect ledger data", detail: "ERP export validated", state: "done" },
      { label: "Analyze variance", detail: "Two anomalies flagged and explained", state: "done" },
      { label: "Generate report", detail: "Delivered to Finance distribution list", state: "done" },
    ],
    sources: ["ERP_Ledger_Aug.xlsx", "Finance Close Policy.pdf"],
  },
  {
    id: "t4",
    name: "Retention Risk Watch",
    goal: "Continuously monitor accounts showing churn signals.",
    status: "running",
    progress: 37,
    startedAt: "Continuous",
    department: "customer_service",
    steps: [
      { label: "Monitor signals", detail: "14 accounts under watch", state: "active" },
      { label: "Escalate", detail: "Threshold not yet reached", state: "pending" },
    ],
    sources: ["Retention Playbook.pdf"],
  },
];

export const insights: Insight[] = [
  {
    id: "i1",
    severity: "critical",
    title: "Sales dropped 18% in Region A",
    detail: "Sustained 3-week decline correlated with fulfilment delays at Hub 2.",
    department: "sales",
    detectedAt: "10:42",
    metric: "-18.4%",
  },
  {
    id: "i2",
    severity: "warning",
    title: "Customer complaints increased 23%",
    detail: "Delivery-related complaint category is the primary driver.",
    department: "customer_service",
    detectedAt: "09:58",
    metric: "+23%",
  },
  {
    id: "i3",
    severity: "warning",
    title: "Monthly revenue below predicted value",
    detail: "Actual revenue trails forecast by 640K for the current period.",
    department: "finance",
    detectedAt: "08:31",
    metric: "-640K",
  },
  {
    id: "i4",
    severity: "info",
    title: "Finance report pending submission",
    detail: "Period close pack has not been submitted by the owning team.",
    department: "finance",
    detectedAt: "Yesterday",
  },
  {
    id: "i5",
    severity: "critical",
    title: "Customer retention risk detected",
    detail: "5 enterprise accounts show combined usage and sentiment decline.",
    department: "customer_service",
    detectedAt: "Yesterday",
    metric: "5 accounts",
  },
];

export const exchanges: DepartmentExchange[] = [
  { id: "e1", from: "AI", department: "finance", text: "Requested monthly revenue data for Region A.", time: "10:44" },
  { id: "e2", from: "DEPARTMENT", department: "finance", text: "Ledger extract provided (Aug period).", time: "10:44" },
  { id: "e3", from: "AI", department: "finance", text: "Compared revenue trend against forecast model.", time: "10:45" },
  { id: "e4", from: "AI", department: "finance", text: "Requested clarification on two credit notes.", time: "10:45" },
  { id: "e5", from: "DEPARTMENT", department: "finance", text: "Clarification received — returns from Hub 2.", time: "10:46" },
  { id: "e6", from: "AI", department: "sales", text: "Sales decline detected in Region A.", time: "10:42" },
  { id: "e7", from: "DEPARTMENT", department: "sales", text: "Providing regional sales data (42,180 records).", time: "10:42" },
  { id: "e8", from: "AI", department: "sales", text: "Segmented decline by product line.", time: "10:43" },
  { id: "e9", from: "AI", department: "customer_service", text: "Requested recent complaint trends.", time: "10:43" },
  { id: "e10", from: "DEPARTMENT", department: "customer_service", text: "Complaint volume +23%, delivery category dominant.", time: "10:44" },
  { id: "e11", from: "AI", department: "operations", text: "Requested hub throughput for last 21 days.", time: "10:45" },
  { id: "e12", from: "DEPARTMENT", department: "operations", text: "Hub 2 throughput down 31%.", time: "10:45" },
  { id: "e13", from: "AI", department: "hr", text: "Checked staffing coverage for Hub 2.", time: "10:46" },
  { id: "e14", from: "DEPARTMENT", department: "hr", text: "Two shift vacancies unfilled since week 32.", time: "10:46" },
  { id: "e15", from: "AI", department: "marketing", text: "Verified no campaign change in Region A.", time: "09:20" },
  { id: "e16", from: "DEPARTMENT", department: "marketing", text: "No campaign changes recorded.", time: "09:21" },
  { id: "e17", from: "AI", department: "it", text: "Verified CRM sync integrity.", time: "08:10" },
  { id: "e18", from: "DEPARTMENT", department: "it", text: "Sync healthy, no failed jobs.", time: "08:11" },
  { id: "e19", from: "AI", department: "design", text: "Requested current packaging asset version.", time: "Yesterday" },
  { id: "e20", from: "DEPARTMENT", department: "design", text: "Asset v4 provided.", time: "Yesterday" },
];

export const liveMeetingScript: DepartmentExchange[] = [
  { id: "l1", from: "AI", department: "sales", text: "Sales decline detected in Region A.", time: "now" },
  { id: "l2", from: "DEPARTMENT", department: "sales", text: "Providing regional sales data.", time: "now" },
  { id: "l3", from: "DEPARTMENT", department: "customer_service", text: "Providing recent complaint trends.", time: "now" },
  { id: "l4", from: "DEPARTMENT", department: "finance", text: "Providing revenue comparison.", time: "now" },
  { id: "l5", from: "AI", department: "operations", text: "Correlation detected with hub throughput.", time: "now" },
  { id: "l6", from: "AI", department: "finance", text: "Preparing management report.", time: "now" },
];

export const schedules: Schedule[] = [
  { id: "s1", task: "Sales Analysis", frequency: "Every Monday · 07:00", nextRun: "Mon 07:00", status: "active", owner: "AI Administrator", department: "sales" },
  { id: "s2", task: "Financial Summary", frequency: "1st of month · 06:00", nextRun: "01 Sep 06:00", status: "active", owner: "Company Admin", department: "finance" },
  { id: "s3", task: "Customer Complaint Monitoring", frequency: "Daily · 09:00", nextRun: "Tomorrow 09:00", status: "active", owner: "Manager", department: "customer_service" },
  { id: "s4", task: "Weekly Management Report", frequency: "Every Friday · 16:00", nextRun: "Fri 16:00", status: "active", owner: "Company Admin", department: "operations" },
  { id: "s5", task: "HR Headcount Snapshot", frequency: "Every 2 weeks", nextRun: "Paused", status: "paused", owner: "Manager", department: "hr" },
];

export const libraryItems: LibraryItem[] = [
  { id: "d1", name: "Company Sales Policy.pdf", category: "Policies", size: "412 KB", updated: "2d ago", access: "All staff", indexed: true },
  { id: "d2", name: "Q2 Revenue Report.xlsx", category: "Reports", size: "1.8 MB", updated: "6h ago", access: "Managers", indexed: true },
  { id: "d3", name: "Customer Service SOP.pdf", category: "SOPs", size: "230 KB", updated: "1w ago", access: "All staff", indexed: true },
  { id: "d4", name: "Hub Logistics Manual.pdf", category: "Manuals", size: "3.4 MB", updated: "3w ago", access: "Managers", indexed: true },
  { id: "d5", name: "CSAT_Q3.csv", category: "Datasets", size: "780 KB", updated: "1d ago", access: "AI only", indexed: true },
  { id: "d6", name: "Board Update — August.docx", category: "Documents", size: "96 KB", updated: "4d ago", access: "Admins", indexed: false },
  { id: "d7", name: "Supplier Correspondence 2026.mbox", category: "Communications", size: "22 MB", updated: "5d ago", access: "Admins", indexed: true },
  { id: "d8", name: "Industry Benchmark 2026.pdf", category: "Reference", size: "5.1 MB", updated: "2w ago", access: "All staff", indexed: true },
  { id: "d9", name: "Finance Close Policy.pdf", category: "Policies", size: "188 KB", updated: "1m ago", access: "Managers", indexed: true },
  { id: "d10", name: "Retention Playbook.pdf", category: "SOPs", size: "540 KB", updated: "3d ago", access: "Managers", indexed: true },
];

export const knowledgeStatus: KnowledgeStatus = {
  documentsIndexed: 1284,
  knowledgeSources: 42,
  lastSync: "4 min ago",
  pendingUpdates: 7,
};

export const auditEntries: AuditEntry[] = [
  { id: "au1", time: "10:42", event: "Sales data retrieved", actor: "AI", department: "sales", status: "ok" },
  { id: "au2", time: "10:43", event: "Customer data requested", actor: "AI", department: "customer_service", status: "ok" },
  { id: "au3", time: "10:44", event: "Finance ledger accessed", actor: "AI", department: "finance", status: "ok" },
  { id: "au4", time: "10:44", event: "Report generated", actor: "AI", status: "ok" },
  { id: "au5", time: "10:46", event: "Email prepared for distribution", actor: "AI", status: "pending" },
  { id: "au6", time: "10:47", event: "Approval requested", actor: "AI", status: "pending" },
  { id: "au7", time: "10:50", event: "Email sent to management list", actor: "Manager", status: "ok" },
  { id: "au8", time: "10:52", event: "External API call blocked by policy", actor: "System", department: "it", status: "denied" },
  { id: "au9", time: "11:02", event: "Autonomy level reviewed", actor: "Company Admin", status: "ok" },
  { id: "au10", time: "11:15", event: "Document indexed into knowledge base", actor: "AI", status: "ok" },
  { id: "au11", time: "11:31", event: "Schedule 'Weekly Management Report' edited", actor: "Manager", status: "ok" },
  { id: "au12", time: "11:44", event: "HR record read attempt outside scope", actor: "AI", department: "hr", status: "denied" },
];

export const recents: RecentItem[] = [
  { id: "r1", label: "Sales Performance Analysis", type: "Task", at: "6 min ago" },
  { id: "r2", label: "Q2 Revenue Report.xlsx", type: "Document", at: "22 min ago" },
  { id: "r3", label: "Finance interaction log", type: "Department", at: "38 min ago" },
  { id: "r4", label: "Customer retention risk detected", type: "Insight", at: "1h ago" },
  { id: "r5", label: "Monthly Revenue Analysis", type: "Report", at: "Yesterday" },
  { id: "r6", label: "Customer Service SOP.pdf", type: "Document", at: "Yesterday" },
];

export const agentConfig: AgentConfig = {
  name: "NX-1",
  role: "Data Intelligence Agent",
  description:
    "Continuously monitors commercial and operational data, investigates anomalies, and reports material events to management.",
  tone: "Concise",
  capabilities: {
    Analytics: true,
    Reporting: true,
    Communication: true,
    "Document generation": true,
    Scheduling: true,
    "Data analysis": true,
    Research: false,
    "Forecast modelling": true,
  },
  tools: {
    Email: true,
    Calendar: true,
    "Company database": true,
    CRM: true,
    ERP: true,
    "File storage": true,
    Analytics: true,
    "External APIs": false,
  },
  permissions: [
    { action: "Read commercial data", mode: "auto" },
    { action: "Read HR records", mode: "restricted" },
    { action: "Modify CRM records", mode: "approval" },
    { action: "Send internal email", mode: "auto" },
    { action: "Send external email", mode: "approval" },
    { action: "Execute ERP transactions", mode: "restricted" },
    { action: "Create scheduled tasks", mode: "approval" },
  ],
  autonomy: 3,
};

export const roleDefinitions: RoleDefinition[] = [
  {
    name: "Company Admin",
    system: true,
    users: 3,
    permissions: {
      "Workspace access": true,
      "Configure AI": true,
      "Manage roles": true,
      "Approve AI actions": true,
      "Manage library": true,
      "View audit log": true,
      "Create schedules": true,
    },
  },
  {
    name: "AI Administrator",
    system: true,
    users: 2,
    permissions: {
      "Workspace access": true,
      "Configure AI": true,
      "Manage roles": false,
      "Approve AI actions": true,
      "Manage library": true,
      "View audit log": true,
      "Create schedules": true,
    },
  },
  {
    name: "Manager",
    system: true,
    users: 24,
    permissions: {
      "Workspace access": true,
      "Configure AI": false,
      "Manage roles": false,
      "Approve AI actions": true,
      "Manage library": true,
      "View audit log": true,
      "Create schedules": true,
    },
  },
  {
    name: "Employee",
    system: true,
    users: 186,
    permissions: {
      "Workspace access": true,
      "Configure AI": false,
      "Manage roles": false,
      "Approve AI actions": false,
      "Manage library": false,
      "View audit log": false,
      "Create schedules": false,
    },
  },
];

export const mailThread: MailMessage[] = [
  {
    id: "m1",
    from: "ai",
    text: "Region A report is prepared. Distribution to the management list requires your approval.",
    time: "10:48",
    delivery: "approval",
  },
  {
    id: "m2",
    from: "user",
    text: "Include the hub throughput comparison before sending.",
    time: "10:51",
  },
  {
    id: "m3",
    from: "ai",
    text: "Added Operations throughput comparison. Report v2 ready for approval.",
    time: "10:52",
    delivery: "approval",
  },
];
