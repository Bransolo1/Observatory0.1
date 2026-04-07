export interface DataSourceItem {
  name: string;
  desc: string;
}

export interface DataSourceCategory {
  type: string;
  items: DataSourceItem[];
}

export const DATA_SOURCE_CATALOG: DataSourceCategory[] = [
  {
    type: "telemetry",
    items: [
      { name: "Amplitude", desc: "Product analytics" },
      { name: "Mixpanel", desc: "Event tracking" },
      { name: "PostHog", desc: "Open-source analytics" },
      { name: "Heap", desc: "Auto-captured events" },
      { name: "Segment", desc: "CDP" },
    ],
  },
  {
    type: "clickstream",
    items: [
      { name: "FullStory", desc: "Session replay & rage clicks" },
      { name: "Hotjar", desc: "Heatmaps & scroll depth" },
      { name: "LogRocket", desc: "Frontend session intelligence" },
    ],
  },
  {
    type: "voc",
    items: [
      { name: "Zendesk", desc: "Support tickets" },
      { name: "Intercom", desc: "Chat + tickets" },
      { name: "App Store Reviews", desc: "iOS / Google Play" },
      { name: "G2 / Capterra", desc: "Review sites" },
      { name: "Sales Calls", desc: "Gong / Chorus" },
    ],
  },
  {
    type: "knowledge",
    items: [
      { name: "Research Docs", desc: "PDF / DOCX uploads" },
      { name: "Notion", desc: "Internal wiki" },
      { name: "Confluence", desc: "Team docs" },
    ],
  },
  {
    type: "market",
    items: [
      { name: "Reddit", desc: "Community mentions" },
      { name: "Hacker News", desc: "Industry chatter" },
      { name: "Product Hunt", desc: "Launch tracking" },
    ],
  },
  {
    type: "social",
    items: [
      { name: "Twitter / X", desc: "Brand & competitor mentions" },
      { name: "LinkedIn", desc: "B2B signal & hires" },
      { name: "TikTok", desc: "Consumer brand sentiment" },
    ],
  },
  {
    type: "academic",
    items: [
      { name: "arXiv", desc: "Pre-print research" },
      { name: "Google Scholar", desc: "Citation-weighted search" },
      { name: "SSRN", desc: "Business & economics papers" },
    ],
  },
  {
    type: "competitor_trends",
    items: [
      { name: "Feature-trend detection", desc: "Auto-detect competitor feature launches" },
      { name: "Changelog monitoring", desc: "Track public roadmap changes" },
      { name: "Pricing-page diffing", desc: "Detect pricing moves" },
    ],
  },
];

export const DATA_SOURCE_TYPE_LABEL: Record<string, string> = {
  telemetry: "Product Telemetry",
  clickstream: "Clickstream & Heatmaps",
  voc: "Voice of Customer",
  knowledge: "Knowledge Base",
  market: "Market Signals",
  social: "Social Listening",
  academic: "Academic Corpora",
  competitor_trends: "Competitor Trend Detection",
};
