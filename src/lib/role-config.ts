/**
 * EAAWP Role Configuration
 *
 * Each role defines the agent persona, tools, capabilities and quick prompts
 * for a specific enterprise job function. Roles are loaded by the platform and
 * used to specialise the Universal AI Core — no code changes are needed to add
 * a new role, only a new RoleConfig entry.
 *
 * Currently implemented: DIGITAL_MARKETING_MANAGER
 * All other roles are RESERVED and must not be instantiated until specified.
 */

import type { ToolGovernance } from "@/services/types";

export type RoleKey =
  | "DIGITAL_MARKETING_MANAGER"
  // Future roles — do not implement yet
  | "SALES_DEVELOPMENT_REP"
  | "FINANCIAL_ANALYST"
  | "HR_BUSINESS_PARTNER"
  | "CUSTOMER_SUCCESS_MANAGER"
  | "OPERATIONS_ANALYST"
  | "DATA_INTELLIGENCE_ANALYST";

export interface RoleToolScope {
  name: string;
  /** Unique key used in the backend MASTER_TOOL_REGISTRY */
  toolKey: string;
  governance: ToolGovernance;
  description: string;
}

export interface RoleConfig {
  key: RoleKey;
  displayName: string;
  agentName: string;
  /** System persona injected into the LLM as the system message */
  systemPersona: string;
  /** Short description shown in the workspace UI */
  description: string;
  quickPrompts: string[];
  toolScopes: RoleToolScope[];
  capabilities: Record<string, boolean>;
  /** Departments this role primarily interacts with */
  primaryDepartments: string[];
}

// ── Digital Marketing Manager ─────────────────────────────────────────────────

export const DIGITAL_MARKETING_MANAGER_CONFIG: RoleConfig = {
  key: "DIGITAL_MARKETING_MANAGER",
  displayName: "Digital Marketing Manager",
  agentName: "Marketing Intelligence Agent",
  systemPersona: `You are the Marketing Intelligence Agent for this company. Your role is to support the Digital Marketing Manager by continuously monitoring campaign performance, analysing audience engagement metrics, surfacing content opportunities, and preparing data-driven marketing reports. You have access to campaign analytics, CRM contact data, content scheduling tools, and the company knowledge base. You operate under strict data governance: you never send external communications without explicit human approval, and you always cite the data sources behind your insights. Your communication style is concise and data-first. Every action you take is logged in the audit trail.`,
  description:
    "Monitors campaigns, surfaces content opportunities, and prepares marketing performance reports.",
  quickPrompts: [
    "Analyse campaign performance this week",
    "What content is trending in our industry?",
    "Prepare monthly marketing report",
    "Which channels are underperforming?",
    "Suggest A/B test ideas for email",
    "Summarise social media engagement",
  ],
  toolScopes: [
    {
      name: "Query Campaign Analytics",
      toolKey: "query_campaign_analytics",
      governance: "enabled",
      description: "Read-only access to campaign performance metrics",
    },
    {
      name: "Fetch Knowledge Base",
      toolKey: "fetch_knowledge_base",
      governance: "enabled",
      description: "Vector search across indexed marketing documents",
    },
    {
      name: "Read CRM Contacts",
      toolKey: "read_crm_contacts",
      governance: "enabled",
      description: "Read audience segmentation and contact lists",
    },
    {
      name: "Generate Report",
      toolKey: "generate_report",
      governance: "enabled",
      description: "Produce structured marketing performance documents",
    },
    {
      name: "Schedule Social Post",
      toolKey: "schedule_social_post",
      governance: "requires_approval",
      description: "Queue social media posts — requires manager approval",
    },
    {
      name: "Send Campaign Email",
      toolKey: "send_campaign_email",
      governance: "requires_approval",
      description: "Send email campaigns — always requires human approval",
    },
    {
      name: "Update CRM Records",
      toolKey: "update_crm_records",
      governance: "requires_approval",
      description: "CRM mutations need manager sign-off",
    },
    {
      name: "Access Financial Data",
      toolKey: "query_finance_erp",
      governance: "disabled",
      description: "Finance ERP is outside this role's scope",
    },
    {
      name: "HR Records Access",
      toolKey: "read_hr_records",
      governance: "disabled",
      description: "HR data is outside this role's scope",
    },
  ],
  capabilities: {
    "Campaign analytics": true,
    "Content generation": true,
    "Competitor research": true,
    "Email drafting": true,
    "Report writing": true,
    "Social media scheduling": true,
    "SEO analysis": true,
    "A/B test suggestions": true,
    "Budget tracking": false,
    "Direct ad spend": false,
  },
  primaryDepartments: ["marketing", "sales", "customer_service"],
};

/** Master registry of all role configurations */
export const ROLE_REGISTRY: Record<RoleKey, RoleConfig | null> = {
  DIGITAL_MARKETING_MANAGER: DIGITAL_MARKETING_MANAGER_CONFIG,
  // Reserved — implement when specified
  SALES_DEVELOPMENT_REP: null,
  FINANCIAL_ANALYST: null,
  HR_BUSINESS_PARTNER: null,
  CUSTOMER_SUCCESS_MANAGER: null,
  OPERATIONS_ANALYST: null,
  DATA_INTELLIGENCE_ANALYST: null,
};

export function getRoleConfig(key: RoleKey): RoleConfig | null {
  return ROLE_REGISTRY[key] ?? null;
}
