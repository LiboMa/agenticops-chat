const pptxgen = require("pptxgenjs");
const pres = new pptxgen();

pres.layout = "LAYOUT_16x9";
pres.author = "AgenticOps Team";
pres.title = "AgenticOps Next-Gen Strategic Roadmap";

// ========== COLOR PALETTE ==========
const C = {
  navy:     "0F2B46",
  teal:     "0891B2",
  cyan:     "06B6D4",
  mint:     "14B8A6",
  dark:     "1E293B",
  slate:    "64748B",
  lightBg:  "F0F9FF",
  white:    "FFFFFF",
  card:     "FFFFFF",
  divider:  "E2E8F0",
  green:    "059669",
  amber:    "D97706",
  red:      "DC2626",
  orange:   "EA580C",
  purple:   "7C3AED",
};

const FONT_H = "Georgia";
const FONT_B = "Calibri";

// Helper: fresh shadow
const shadow = () => ({ type: "outer", blur: 6, offset: 2, angle: 135, color: "000000", opacity: 0.10 });

// ========== SLIDE 1: TITLE ==========
{
  const s = pres.addSlide();
  s.background = { color: C.navy };
  // Top accent bar
  s.addShape(pres.shapes.RECTANGLE, { x: 0, y: 0, w: 10, h: 0.06, fill: { color: C.cyan } });
  // Title
  s.addText("AgenticOps", { x: 0.8, y: 1.2, w: 8, h: 0.9, fontSize: 48, fontFace: FONT_H, color: C.cyan, bold: true, margin: 0 });
  s.addText("Next-Gen AIOps Strategic Roadmap", { x: 0.8, y: 2.1, w: 8, h: 0.7, fontSize: 28, fontFace: FONT_H, color: C.white, margin: 0 });
  s.addText("Agent-First RCA | Self-Evolving Skills | Knowledge Sediment", { x: 0.8, y: 2.85, w: 8, h: 0.5, fontSize: 16, fontFace: FONT_B, color: C.slate, margin: 0 });
  // Bottom info
  s.addShape(pres.shapes.RECTANGLE, { x: 0, y: 4.8, w: 10, h: 0.825, fill: { color: "0A1F33" } });
  s.addText("Post-MVP Strategic Planning  |  2026 Q2 - 2028+  |  50 Tasks across 4 Phases", { x: 0.8, y: 4.95, w: 8.4, h: 0.5, fontSize: 13, fontFace: FONT_B, color: C.slate, margin: 0 });
}

// ========== SLIDE 2: EXECUTIVE SUMMARY ==========
{
  const s = pres.addSlide();
  s.background = { color: C.lightBg };
  s.addText("Executive Summary", { x: 0.8, y: 0.35, w: 8, h: 0.6, fontSize: 32, fontFace: FONT_H, color: C.navy, bold: true, margin: 0 });
  s.addShape(pres.shapes.RECTANGLE, { x: 0.8, y: 0.95, w: 1.2, h: 0.04, fill: { color: C.teal } });

  // Left column
  s.addShape(pres.shapes.RECTANGLE, { x: 0.5, y: 1.3, w: 4.3, h: 3.8, fill: { color: C.white }, shadow: shadow() });
  s.addText("Core Vision", { x: 0.8, y: 1.45, w: 3.8, h: 0.4, fontSize: 16, fontFace: FONT_H, color: C.teal, bold: true, margin: 0 });
  s.addText([
    { text: "AgenticOps is an intelligent platform that uses existing tools, accumulates operational experience, autonomously takes over operations, self-repairs, and self-iterates.", options: { fontSize: 13, fontFace: FONT_B, color: C.dark, breakLine: true, lineSpacingMultiple: 1.3 } },
    { text: "", options: { breakLine: true, fontSize: 8 } },
    { text: "NOT a monitoring tool", options: { fontSize: 12, fontFace: FONT_B, color: C.red, bold: true, breakLine: true } },
    { text: "NOT a data platform", options: { fontSize: 12, fontFace: FONT_B, color: C.red, bold: true, breakLine: true } },
    { text: "NOT a script executor", options: { fontSize: 12, fontFace: FONT_B, color: C.red, bold: true, breakLine: true } },
    { text: "", options: { breakLine: true, fontSize: 8 } },
    { text: "Like a real SRE: gets alerts, investigates, fixes, learns. Except it never sleeps and never forgets.", options: { fontSize: 12, fontFace: FONT_B, color: C.slate, italic: true } },
  ], { x: 0.8, y: 1.9, w: 3.8, h: 3.0 });

  // Right column - key numbers
  s.addShape(pres.shapes.RECTANGLE, { x: 5.2, y: 1.3, w: 4.3, h: 3.8, fill: { color: C.white }, shadow: shadow() });
  s.addText("Roadmap at a Glance", { x: 5.5, y: 1.45, w: 3.8, h: 0.4, fontSize: 16, fontFace: FONT_H, color: C.teal, bold: true, margin: 0 });

  const stats = [
    { num: "50", label: "Total Tasks" },
    { num: "4", label: "Phases (2026-2028+)" },
    { num: "28", label: "Near-Term Priority Tasks" },
    { num: "11", label: "Academic Paper References" },
  ];
  stats.forEach((st, i) => {
    const y = 2.0 + i * 0.75;
    s.addText(st.num, { x: 5.5, y, w: 1.2, h: 0.55, fontSize: 32, fontFace: FONT_H, color: C.teal, bold: true, align: "center", valign: "middle", margin: 0 });
    s.addText(st.label, { x: 6.7, y: y + 0.08, w: 2.6, h: 0.45, fontSize: 14, fontFace: FONT_B, color: C.dark, valign: "middle", margin: 0 });
  });
}

// ========== SLIDE 3: MARKET PAIN POINTS ==========
{
  const s = pres.addSlide();
  s.background = { color: C.lightBg };
  s.addText("Market Pain Points We Solve", { x: 0.8, y: 0.35, w: 8, h: 0.6, fontSize: 32, fontFace: FONT_H, color: C.navy, bold: true, margin: 0 });
  s.addShape(pres.shapes.RECTANGLE, { x: 0.8, y: 0.95, w: 1.2, h: 0.04, fill: { color: C.teal } });

  const pains = [
    { title: "Alert Fatigue", desc: "SRE teams drown in alerts. No intelligent classification or dedup. Every alert starts investigation from zero.", color: C.red },
    { title: "Slow RCA (MTTR)", desc: "Average MTTR > 30min. SREs switch between 5+ tools. No automated evidence collection or confidence scoring.", color: C.orange },
    { title: "Knowledge Loss", desc: "When senior SRE leaves, knowledge walks out the door. No institutional memory. Every new hire starts from scratch.", color: C.amber },
    { title: "Runbook Staleness", desc: "80% of runbooks are outdated. No one maintains them. Infrastructure changes but SOPs don't.", color: C.amber },
    { title: "Tool Fragmentation", desc: "Datadog for metrics, CloudWatch for logs, kubectl for K8s, CloudTrail for changes. No unified investigation path.", color: C.orange },
    { title: "No Verification Loop", desc: "Fix deployed but no automated check. SRE stares at dashboards for 15min. No Ground Truth feedback.", color: C.red },
  ];

  pains.forEach((p, i) => {
    const col = i < 3 ? 0 : 1;
    const row = i % 3;
    const x = 0.5 + col * 4.7;
    const y = 1.2 + row * 1.35;
    s.addShape(pres.shapes.RECTANGLE, { x, y, w: 4.4, h: 1.15, fill: { color: C.white }, shadow: shadow() });
    s.addShape(pres.shapes.RECTANGLE, { x, y, w: 0.07, h: 1.15, fill: { color: p.color } });
    s.addText(p.title, { x: x + 0.25, y: y + 0.1, w: 3.9, h: 0.35, fontSize: 14, fontFace: FONT_H, color: C.dark, bold: true, margin: 0 });
    s.addText(p.desc, { x: x + 0.25, y: y + 0.45, w: 3.9, h: 0.6, fontSize: 11, fontFace: FONT_B, color: C.slate, margin: 0 });
  });
}

// ========== SLIDE 4: COMPETITIVE LANDSCAPE ==========
{
  const s = pres.addSlide();
  s.background = { color: C.lightBg };
  s.addText("Competitive Landscape", { x: 0.8, y: 0.35, w: 8, h: 0.6, fontSize: 32, fontFace: FONT_H, color: C.navy, bold: true, margin: 0 });
  s.addShape(pres.shapes.RECTANGLE, { x: 0.8, y: 0.95, w: 1.2, h: 0.04, fill: { color: C.teal } });

  const headerOpts = { fill: { color: C.navy }, color: C.white, bold: true, fontSize: 11, fontFace: FONT_B, align: "center", valign: "middle" };
  const cellOpts = { fontSize: 10, fontFace: FONT_B, color: C.dark, align: "center", valign: "middle" };
  const yesOpts = { ...cellOpts, color: C.green, bold: true };
  const noOpts = { ...cellOpts, color: C.red };

  const rows = [
    [
      { text: "Capability", options: { ...headerOpts, align: "left" } },
      { text: "AgenticOps", options: headerOpts },
      { text: "PagerDuty\nOpsGenie", options: headerOpts },
      { text: "HolmesGPT\nKeep", options: headerOpts },
      { text: "RCACopilot\n(Microsoft)", options: headerOpts },
    ],
    [{ text: "Agent-First RCA", options: { ...cellOpts, align: "left" } }, { text: "Yes", options: yesOpts }, { text: "No", options: noOpts }, { text: "Partial", options: cellOpts }, { text: "Template", options: cellOpts }],
    [{ text: "Self-Evolving Skills", options: { ...cellOpts, align: "left" } }, { text: "Yes", options: yesOpts }, { text: "No", options: noOpts }, { text: "No", options: noOpts }, { text: "No", options: noOpts }],
    [{ text: "Evidence-Weighted Confidence", options: { ...cellOpts, align: "left" } }, { text: "8-level", options: yesOpts }, { text: "No", options: noOpts }, { text: "No", options: noOpts }, { text: "Binary", options: cellOpts }],
    [{ text: "Memory + Learning Loop", options: { ...cellOpts, align: "left" } }, { text: "4-type", options: yesOpts }, { text: "No", options: noOpts }, { text: "No", options: noOpts }, { text: "No", options: noOpts }],
    [{ text: "PostAction Verification", options: { ...cellOpts, align: "left" } }, { text: "T0-T3", options: yesOpts }, { text: "No", options: noOpts }, { text: "No", options: noOpts }, { text: "No", options: noOpts }],
    [{ text: "Human Ground Truth Loop", options: { ...cellOpts, align: "left" } }, { text: "Yes", options: yesOpts }, { text: "No", options: noOpts }, { text: "No", options: noOpts }, { text: "Partial", options: cellOpts }],
    [{ text: "Safe Remediation (L0-L3)", options: { ...cellOpts, align: "left" } }, { text: "5-layer", options: yesOpts }, { text: "No", options: noOpts }, { text: "No", options: noOpts }, { text: "No", options: noOpts }],
    [{ text: "AWS-Native Deep Integration", options: { ...cellOpts, align: "left" } }, { text: "Yes", options: yesOpts }, { text: "Partial", options: cellOpts }, { text: "Partial", options: cellOpts }, { text: "Azure", options: cellOpts }],
  ];

  s.addTable(rows, {
    x: 0.5, y: 1.2, w: 9.0,
    colW: [2.5, 1.5, 1.5, 1.5, 2.0],
    border: { pt: 0.5, color: C.divider },
    rowH: [0.45, 0.38, 0.38, 0.38, 0.38, 0.38, 0.38, 0.38, 0.38],
    autoPage: false,
  });

  s.addText("Source: ClawOps Agent-First AIOps Architecture analysis + market research (2026)", { x: 0.5, y: 5.0, w: 9, h: 0.3, fontSize: 9, fontFace: FONT_B, color: C.slate, italic: true, margin: 0 });
}

// ========== SLIDE 5: AGENT-FIRST ARCHITECTURE ==========
{
  const s = pres.addSlide();
  s.background = { color: C.navy };
  s.addShape(pres.shapes.RECTANGLE, { x: 0, y: 0, w: 10, h: 0.06, fill: { color: C.cyan } });
  s.addText("Agent-First Framework", { x: 0.8, y: 0.3, w: 8, h: 0.6, fontSize: 32, fontFace: FONT_H, color: C.white, bold: true, margin: 0 });
  s.addText("Perceive  >  Plan  >  Act  >  Decide  >  Verify  >  Learn", { x: 0.8, y: 0.85, w: 8, h: 0.35, fontSize: 15, fontFace: FONT_B, color: C.cyan, margin: 0 });

  const phases = [
    { name: "PERCEIVE", desc: "Alert details\nMemory recall\nService context", col: C.teal },
    { name: "PLAN", desc: "Prompt Optimization\nWisdom Roadmap\nFirst-principles", col: "0E7490" },
    { name: "ACT", desc: "Connectors query\nEvidence collect\nAdaptive path", col: C.cyan },
    { name: "DECIDE", desc: "Evidence synthesis\nConfidence score\nRCA output", col: C.mint },
    { name: "VERIFY", desc: "PostAction T0-T3\nHuman review\nSelf-check", col: C.green },
    { name: "LEARN", desc: "Memory write\nWisdom update\nSkill evolve", col: "047857" },
  ];

  phases.forEach((p, i) => {
    const x = 0.35 + i * 1.55;
    s.addShape(pres.shapes.RECTANGLE, { x, y: 1.5, w: 1.4, h: 3.2, fill: { color: p.col }, shadow: shadow() });
    s.addText(p.name, { x, y: 1.6, w: 1.4, h: 0.55, fontSize: 13, fontFace: FONT_H, color: C.white, bold: true, align: "center", valign: "middle", margin: 0 });
    s.addShape(pres.shapes.RECTANGLE, { x: x + 0.15, y: 2.2, w: 1.1, h: 0.02, fill: { color: C.white } });
    s.addText(p.desc, { x: x + 0.1, y: 2.35, w: 1.2, h: 2.1, fontSize: 10, fontFace: FONT_B, color: C.white, valign: "top", margin: 0 });
    // Arrow between
    if (i < 5) {
      s.addText(">", { x: x + 1.38, y: 2.7, w: 0.2, h: 0.4, fontSize: 20, fontFace: FONT_B, color: C.slate, align: "center", valign: "middle", margin: 0 });
    }
  });

  s.addText("No pre-built topology needed. Agent investigates on-the-fly using experience + tools.", { x: 0.8, y: 4.9, w: 8, h: 0.4, fontSize: 12, fontFace: FONT_B, color: C.slate, italic: true, margin: 0 });
}

// ========== SLIDE 6: INNOVATION STACK ==========
{
  const s = pres.addSlide();
  s.background = { color: C.lightBg };
  s.addText("Innovation Stack", { x: 0.8, y: 0.35, w: 8, h: 0.6, fontSize: 32, fontFace: FONT_H, color: C.navy, bold: true, margin: 0 });
  s.addShape(pres.shapes.RECTANGLE, { x: 0.8, y: 0.95, w: 1.2, h: 0.04, fill: { color: C.teal } });

  const layers = [
    { name: "Prompt Optimization", desc: "Auto-optimized investigation prompts. +21% accuracy.", paper: "eARCO (Microsoft, arXiv:2504.11505)", color: C.teal },
    { name: "Self-Evolving Skills", desc: "Every resolved incident becomes a reusable skill.", paper: "OpsAgent (arXiv:2510.24145)", color: "0E7490" },
    { name: "Agent-First Planning", desc: "LLM-driven investigation, not static graphs.", paper: "arXiv:2602.09937", color: C.cyan },
    { name: "Result Verification", desc: "Independent T0-T3 verification + human Ground Truth.", paper: "arXiv:2601.22208", color: C.mint },
    { name: "Confidence Calibration", desc: "Evidence-weighted + human-calibrated scoring.", paper: "CCAR (arXiv:2603.08736)", color: C.green },
    { name: "Knowledge Sediment", desc: "Episodic > Procedural > Semantic > Skill > SOP.", paper: "Pearl's Causal Framework", color: "047857" },
  ];

  layers.forEach((l, i) => {
    const y = 1.2 + i * 0.7;
    s.addShape(pres.shapes.RECTANGLE, { x: 0.5, y, w: 9.0, h: 0.58, fill: { color: C.white }, shadow: shadow() });
    s.addShape(pres.shapes.RECTANGLE, { x: 0.5, y, w: 0.07, h: 0.58, fill: { color: l.color } });
    s.addText(l.name, { x: 0.75, y, w: 2.2, h: 0.58, fontSize: 13, fontFace: FONT_H, color: C.dark, bold: true, valign: "middle", margin: 0 });
    s.addText(l.desc, { x: 3.0, y, w: 3.8, h: 0.58, fontSize: 11, fontFace: FONT_B, color: C.dark, valign: "middle", margin: 0 });
    s.addText(l.paper, { x: 6.9, y, w: 2.5, h: 0.58, fontSize: 9, fontFace: FONT_B, color: C.slate, italic: true, valign: "middle", margin: 0 });
  });

  s.addText("11 academic papers, 180,000+ real incidents data from Microsoft, production-proven patterns", { x: 0.5, y: 5.35, w: 9, h: 0.25, fontSize: 10, fontFace: FONT_B, color: C.slate, italic: true, margin: 0 });
}

// ========== SLIDE 7: FOUR-PHASE ROADMAP OVERVIEW ==========
{
  const s = pres.addSlide();
  s.background = { color: C.lightBg };
  s.addText("Four-Phase Roadmap", { x: 0.8, y: 0.35, w: 8, h: 0.6, fontSize: 32, fontFace: FONT_H, color: C.navy, bold: true, margin: 0 });
  s.addShape(pres.shapes.RECTANGLE, { x: 0.8, y: 0.95, w: 1.2, h: 0.04, fill: { color: C.teal } });

  const phaseData = [
    { name: "Phase 1", sub: "Foundation", time: "Q2 2026", tasks: "21 Tasks", desc: "Connectors, Service Model,\nPrompt Engine, Evidence", color: C.teal, tag: "IMMEDIATE" },
    { name: "Phase 2", sub: "Verify + Learn", time: "Q3-Q4 2026", tasks: "14 Tasks", desc: "PostActionValidator,\nHuman Review, Wisdom, Calibration", color: "0E7490", tag: "SHORT-TERM" },
    { name: "Phase 3", sub: "Self-Evolution", time: "2027", tasks: "8 Tasks", desc: "SkillGapDetector, SOPAutoWriter,\nSandbox Validation, Self-Verify", color: C.purple, tag: "RESEARCH" },
    { name: "Phase 4", sub: "Autonomous Ops", time: "2028+", tasks: "7 Tasks", desc: "Cross-Service Correlation,\nProactive Detection, Graduated Autonomy", color: C.slate, tag: "VISION" },
  ];

  // Timeline line
  s.addShape(pres.shapes.RECTANGLE, { x: 0.8, y: 2.35, w: 8.4, h: 0.04, fill: { color: C.divider } });

  phaseData.forEach((p, i) => {
    const x = 0.5 + i * 2.3;
    // Timeline dot
    s.addShape(pres.shapes.OVAL, { x: x + 0.85, y: 2.18, w: 0.22, h: 0.22, fill: { color: p.color } });
    // Card
    s.addShape(pres.shapes.RECTANGLE, { x, y: 2.75, w: 2.1, h: 2.55, fill: { color: C.white }, shadow: shadow() });
    s.addShape(pres.shapes.RECTANGLE, { x, y: 2.75, w: 2.1, h: 0.5, fill: { color: p.color } });
    s.addText(p.name, { x, y: 2.78, w: 2.1, h: 0.25, fontSize: 14, fontFace: FONT_H, color: C.white, bold: true, align: "center", margin: 0 });
    s.addText(p.sub, { x, y: 3.0, w: 2.1, h: 0.22, fontSize: 10, fontFace: FONT_B, color: C.white, align: "center", margin: 0 });
    // Content
    s.addText(p.time, { x: x + 0.15, y: 3.35, w: 1.8, h: 0.3, fontSize: 12, fontFace: FONT_B, color: C.dark, bold: true, margin: 0 });
    s.addText(p.tasks, { x: x + 0.15, y: 3.6, w: 1.8, h: 0.25, fontSize: 11, fontFace: FONT_B, color: p.color, bold: true, margin: 0 });
    s.addText(p.desc, { x: x + 0.15, y: 3.9, w: 1.8, h: 1.0, fontSize: 10, fontFace: FONT_B, color: C.slate, margin: 0 });
    // Tag
    s.addText(p.tag, { x: x + 0.15, y: 1.7, w: 1.0, h: 0.3, fontSize: 8, fontFace: FONT_B, color: p.color, bold: true, margin: 0 });
  });
}

// ========== SLIDE 8: PHASE 1 OVERVIEW ==========
{
  const s = pres.addSlide();
  s.background = { color: C.lightBg };
  s.addText("Phase 1: Foundation", { x: 0.8, y: 0.35, w: 6, h: 0.6, fontSize: 32, fontFace: FONT_H, color: C.navy, bold: true, margin: 0 });
  s.addText("Q2 2026  |  21 Tasks  |  16 New Files  |  9 Modified Files", { x: 0.8, y: 0.9, w: 8, h: 0.35, fontSize: 13, fontFace: FONT_B, color: C.teal, margin: 0 });

  const tracks = [
    { name: "Connector Framework", tasks: "7 tasks", items: "ConnectorBase ABC\nRegistry + YAML config\nAWS (wrap existing)\nKubernetes (wrap existing)\nDatadog API (new)\nPrometheus PromQL (new)\nAgent query tools", color: C.teal },
    { name: "Service Model", tasks: "4 tasks", items: "DB tables (Service,\nServiceResource,\nServiceDependency)\nCRUD agent tools\nAPI endpoints\nChat-based discovery", color: "0E7490" },
    { name: "Prompt Engine", tasks: "6 tasks", items: "Evidence model + weights\nAlert Classifier\nFew-Shot Retriever\nStrategy Selector\nToken-budgeted Assembler\nSkills indexing", color: C.cyan },
    { name: "Integration", tasks: "4 tasks", items: "Wire into RCA Agent\nWire into Main Agent\nDB migration verify\nE2E smoke test", color: C.mint },
  ];

  tracks.forEach((t, i) => {
    const x = 0.35 + i * 2.4;
    s.addShape(pres.shapes.RECTANGLE, { x, y: 1.5, w: 2.2, h: 3.7, fill: { color: C.white }, shadow: shadow() });
    s.addShape(pres.shapes.RECTANGLE, { x, y: 1.5, w: 2.2, h: 0.55, fill: { color: t.color } });
    s.addText(t.name, { x, y: 1.52, w: 2.2, h: 0.3, fontSize: 12, fontFace: FONT_H, color: C.white, bold: true, align: "center", margin: 0 });
    s.addText(t.tasks, { x, y: 1.8, w: 2.2, h: 0.22, fontSize: 10, fontFace: FONT_B, color: C.white, align: "center", margin: 0 });
    s.addText(t.items, { x: x + 0.15, y: 2.2, w: 1.9, h: 2.8, fontSize: 11, fontFace: FONT_B, color: C.dark, margin: 0 });
  });

  s.addText("4 parallel tracks converge at Integration (Task 16). No sequential bottleneck.", { x: 0.5, y: 5.15, w: 9, h: 0.3, fontSize: 11, fontFace: FONT_B, color: C.slate, italic: true, margin: 0 });
}

// ========== SLIDE 9: PHASE 1 DETAIL - CONNECTORS ==========
{
  const s = pres.addSlide();
  s.background = { color: C.lightBg };
  s.addText("Phase 1: Connector Architecture", { x: 0.8, y: 0.35, w: 8, h: 0.6, fontSize: 28, fontFace: FONT_H, color: C.navy, bold: true, margin: 0 });
  s.addShape(pres.shapes.RECTANGLE, { x: 0.8, y: 0.9, w: 1.2, h: 0.04, fill: { color: C.teal } });

  // Left: concept
  s.addShape(pres.shapes.RECTANGLE, { x: 0.5, y: 1.2, w: 4.4, h: 4.0, fill: { color: C.white }, shadow: shadow() });
  s.addText("Design Philosophy", { x: 0.7, y: 1.3, w: 4.0, h: 0.35, fontSize: 15, fontFace: FONT_H, color: C.teal, bold: true, margin: 0 });
  s.addText([
    { text: "Admin provides credentials + endpoints.", options: { bold: true, fontSize: 12, fontFace: FONT_B, color: C.dark, breakLine: true } },
    { text: "Agent decides what to query.", options: { bold: true, fontSize: 12, fontFace: FONT_B, color: C.teal, breakLine: true } },
    { text: "", options: { breakLine: true, fontSize: 6 } },
    { text: "No predefined query sequences. Each investigation step is an autonomous decision based on findings so far.", options: { fontSize: 11, fontFace: FONT_B, color: C.slate, breakLine: true } },
    { text: "", options: { breakLine: true, fontSize: 6 } },
    { text: "Guardrails:", options: { bold: true, fontSize: 12, fontFace: FONT_B, color: C.dark, breakLine: true } },
    { text: "Read-only by default", options: { bullet: true, fontSize: 11, fontFace: FONT_B, color: C.dark, breakLine: true } },
    { text: "Rate limiting per connector", options: { bullet: true, fontSize: 11, fontFace: FONT_B, color: C.dark, breakLine: true } },
    { text: "Cost awareness for pay-per-query APIs", options: { bullet: true, fontSize: 11, fontFace: FONT_B, color: C.dark, breakLine: true } },
    { text: "Write ops via Executor Agent (L0-L3)", options: { bullet: true, fontSize: 11, fontFace: FONT_B, color: C.dark, breakLine: true } },
    { text: "", options: { breakLine: true, fontSize: 6 } },
    { text: "No connector? Agent works with what it has.", options: { fontSize: 11, fontFace: FONT_B, color: C.slate, italic: true } },
  ], { x: 0.7, y: 1.7, w: 4.0, h: 3.3 });

  // Right: connector list
  s.addShape(pres.shapes.RECTANGLE, { x: 5.2, y: 1.2, w: 4.3, h: 4.0, fill: { color: C.white }, shadow: shadow() });
  s.addText("Initial Connectors", { x: 5.4, y: 1.3, w: 4.0, h: 0.35, fontSize: 15, fontFace: FONT_H, color: C.teal, bold: true, margin: 0 });

  const connectors = [
    { name: "AWS", status: "Wrap existing", detail: "CloudTrail, CloudWatch, AWS CLI" },
    { name: "Kubernetes", status: "Wrap existing", detail: "kubectl, events, logs" },
    { name: "Datadog", status: "New", detail: "Metrics, logs, monitors, events" },
    { name: "Prometheus", status: "New", detail: "PromQL queries, alerts, targets" },
  ];

  connectors.forEach((c, i) => {
    const y = 1.8 + i * 0.8;
    s.addShape(pres.shapes.RECTANGLE, { x: 5.4, y, w: 3.9, h: 0.65, fill: { color: C.lightBg } });
    s.addText(c.name, { x: 5.55, y, w: 1.5, h: 0.35, fontSize: 13, fontFace: FONT_H, color: C.dark, bold: true, margin: 0 });
    s.addText(c.status, { x: 7.3, y: y + 0.02, w: 1.5, h: 0.3, fontSize: 9, fontFace: FONT_B, color: c.status === "New" ? C.teal : C.slate, bold: true, align: "right", margin: 0 });
    s.addText(c.detail, { x: 5.55, y: y + 0.32, w: 3.5, h: 0.3, fontSize: 10, fontFace: FONT_B, color: C.slate, margin: 0 });
  });

  s.addText("config/connectors.yaml (gitignored, admin-managed)", { x: 5.4, y: 5.0, w: 3.9, h: 0.2, fontSize: 9, fontFace: FONT_B, color: C.slate, italic: true, margin: 0 });
}

// ========== SLIDE 10: PHASE 1 - PROMPT ENGINE ==========
{
  const s = pres.addSlide();
  s.background = { color: C.lightBg };
  s.addText("Phase 1: Prompt Optimization Engine", { x: 0.8, y: 0.35, w: 8, h: 0.6, fontSize: 28, fontFace: FONT_H, color: C.navy, bold: true, margin: 0 });
  s.addText("Based on eARCO (Microsoft): Prompt > RAG > Fine-tuning, +21% accuracy on 180K incidents", { x: 0.8, y: 0.9, w: 8, h: 0.3, fontSize: 12, fontFace: FONT_B, color: C.teal, margin: 0 });

  // Flow: 4 components
  const components = [
    { name: "Alert\nClassifier", desc: "Alert text\n> Category\n> Pattern label", y: 1.5 },
    { name: "Strategy\nSelector", desc: "Pattern\n> Wisdom lookup\n> Default fallback", y: 1.5 },
    { name: "Few-Shot\nRetriever", desc: "Category\n> KB vector search\n> Top-K cases", y: 1.5 },
    { name: "Prompt\nAssembler", desc: "Strategy + Cases\n+ Service context\n> 3000 token budget", y: 1.5 },
  ];

  components.forEach((c, i) => {
    const x = 0.5 + i * 2.35;
    s.addShape(pres.shapes.RECTANGLE, { x, y: c.y, w: 2.1, h: 1.8, fill: { color: C.white }, shadow: shadow() });
    s.addShape(pres.shapes.RECTANGLE, { x, y: c.y, w: 2.1, h: 0.55, fill: { color: C.teal } });
    s.addText(c.name, { x, y: c.y + 0.02, w: 2.1, h: 0.5, fontSize: 12, fontFace: FONT_H, color: C.white, bold: true, align: "center", valign: "middle", margin: 0 });
    s.addText(c.desc, { x: x + 0.12, y: c.y + 0.65, w: 1.85, h: 1.0, fontSize: 10, fontFace: FONT_B, color: C.slate, margin: 0 });
    if (i < 3) {
      s.addText(">", { x: x + 2.05, y: 2.1, w: 0.35, h: 0.4, fontSize: 20, fontFace: FONT_B, color: C.teal, align: "center", valign: "middle", margin: 0 });
    }
  });

  // Before vs After
  s.addShape(pres.shapes.RECTANGLE, { x: 0.5, y: 3.6, w: 4.3, h: 1.6, fill: { color: "FEF2F2" }, shadow: shadow() });
  s.addText("BEFORE (hand-written prompt)", { x: 0.65, y: 3.65, w: 4, h: 0.3, fontSize: 11, fontFace: FONT_H, color: C.red, bold: true, margin: 0 });
  s.addText('"You are an AIOps expert. Analyze this alert."\n> Agent wanders, checks random metrics, slow', { x: 0.65, y: 3.95, w: 4, h: 1.0, fontSize: 10, fontFace: FONT_B, color: C.dark, italic: true, margin: 0 });

  s.addShape(pres.shapes.RECTANGLE, { x: 5.2, y: 3.6, w: 4.3, h: 1.6, fill: { color: "F0FDF4" }, shadow: shadow() });
  s.addText("AFTER (optimized prompt)", { x: 5.35, y: 3.65, w: 4, h: 0.3, fontSize: 11, fontFace: FONT_H, color: C.green, bold: true, margin: 0 });
  s.addText('"ALB 5xx on payment-service. Historical: 85%\ndeployment-related. Steps: 1) CloudTrail 2) ECS\n3) Redis. Evidence from 3 past cases attached."', { x: 5.35, y: 3.95, w: 4, h: 1.0, fontSize: 10, fontFace: FONT_B, color: C.dark, italic: true, margin: 0 });
}

// ========== SLIDE 11: PHASE 2 OVERVIEW ==========
{
  const s = pres.addSlide();
  s.background = { color: C.lightBg };
  s.addText("Phase 2: Verification + Learning", { x: 0.8, y: 0.35, w: 8, h: 0.6, fontSize: 32, fontFace: FONT_H, color: C.navy, bold: true, margin: 0 });
  s.addText("Q3-Q4 2026  |  14 Tasks  |  The Learning Loop", { x: 0.8, y: 0.9, w: 8, h: 0.35, fontSize: 13, fontFace: FONT_B, color: "0E7490", margin: 0 });

  // 3 columns
  const cols = [
    { name: "PostActionValidator", tasks: "3 tasks", items: "T0 (30s): Command succeeded?\nT1 (2min): Metric improving?\nT2 (5min): Alert cleared?\nT3 (15min): No new alerts?\n\nVerdicts:\nSUCCESS > auto-resolve\nPARTIAL > keep open\nFAILED > rollback to RCA\nUNCERTAIN > human decides", color: C.teal },
    { name: "Human Review", tasks: "4 tasks", items: "3 review points:\n\n1. RCA Review\n   Accurate / Partial / Inaccurate\n\n2. Fix Effectiveness (24h)\n   Resolved / Mitigated / Unresolved\n\n3. Service Model Confirm\n\nOne click = one Ground Truth\nCalibration updated incrementally", color: "0E7490" },
    { name: "Wisdom Roadmap", tasks: "5 tasks", items: "Pattern > Strategy mapping:\n\ncache_memory_exhaustion\n> check deploys first (85%)\n\nDistilled from resolved cases\nTop-K retrieval (max 3)\n2000 token budget\n\n4-Layer Memory:\nEpisodic > Procedural >\nSemantic > Skill > SOP", color: C.purple },
  ];

  cols.forEach((c, i) => {
    const x = 0.35 + i * 3.15;
    s.addShape(pres.shapes.RECTANGLE, { x, y: 1.5, w: 2.95, h: 3.8, fill: { color: C.white }, shadow: shadow() });
    s.addShape(pres.shapes.RECTANGLE, { x, y: 1.5, w: 2.95, h: 0.55, fill: { color: c.color } });
    s.addText(c.name, { x, y: 1.52, w: 2.95, h: 0.3, fontSize: 13, fontFace: FONT_H, color: C.white, bold: true, align: "center", margin: 0 });
    s.addText(c.tasks, { x, y: 1.8, w: 2.95, h: 0.22, fontSize: 10, fontFace: FONT_B, color: C.white, align: "center", margin: 0 });
    s.addText(c.items, { x: x + 0.15, y: 2.2, w: 2.65, h: 2.9, fontSize: 10, fontFace: FONT_B, color: C.dark, margin: 0 });
  });
}

// ========== SLIDE 12: PHASE 2 - EVIDENCE WEIGHTING ==========
{
  const s = pres.addSlide();
  s.background = { color: C.lightBg };
  s.addText("Evidence-Weighted Confidence System", { x: 0.8, y: 0.35, w: 8, h: 0.6, fontSize: 28, fontFace: FONT_H, color: C.navy, bold: true, margin: 0 });
  s.addShape(pres.shapes.RECTANGLE, { x: 0.8, y: 0.9, w: 1.2, h: 0.04, fill: { color: C.teal } });

  // Source weights chart
  const sources = [
    { name: "CloudTrail change", weight: 0.95 },
    { name: "APM trace error", weight: 0.90 },
    { name: "Deployment match", weight: 0.85 },
    { name: "CloudWatch metric", weight: 0.80 },
    { name: "Log pattern match", weight: 0.75 },
    { name: "SG/Network analysis", weight: 0.70 },
    { name: "KB similar case", weight: 0.50 },
    { name: "LLM pure inference", weight: 0.30 },
  ];

  s.addText("Evidence Source Weights", { x: 0.5, y: 1.15, w: 4.5, h: 0.35, fontSize: 15, fontFace: FONT_H, color: C.dark, bold: true, margin: 0 });

  sources.forEach((src, i) => {
    const y = 1.6 + i * 0.44;
    const barW = src.weight * 4.0;
    const color = src.weight >= 0.8 ? C.green : src.weight >= 0.6 ? C.amber : C.red;
    s.addText(src.name, { x: 0.5, y, w: 2.0, h: 0.35, fontSize: 10, fontFace: FONT_B, color: C.dark, align: "right", valign: "middle", margin: 0 });
    s.addShape(pres.shapes.RECTANGLE, { x: 2.6, y: y + 0.07, w: barW, h: 0.22, fill: { color } });
    s.addText(src.weight.toFixed(2), { x: 2.6 + barW + 0.1, y, w: 0.5, h: 0.35, fontSize: 10, fontFace: FONT_B, color: C.dark, bold: true, valign: "middle", margin: 0 });
  });

  // Right: calibration explanation
  s.addShape(pres.shapes.RECTANGLE, { x: 5.5, y: 1.15, w: 3.8, h: 4.2, fill: { color: C.white }, shadow: shadow() });
  s.addText("Two-Layer Calibration", { x: 5.7, y: 1.25, w: 3.2, h: 0.35, fontSize: 15, fontFace: FONT_H, color: C.teal, bold: true, margin: 0 });
  s.addText([
    { text: "Layer 1: Evidence-Weighted", options: { bold: true, fontSize: 12, fontFace: FONT_B, color: C.dark, breakLine: true } },
    { text: "Weighted average of evidence chain\nper data source reliability\n", options: { fontSize: 10, fontFace: FONT_B, color: C.slate, breakLine: true } },
    { text: "Layer 2: Human-Calibrated", options: { bold: true, fontSize: 12, fontFace: FONT_B, color: C.dark, breakLine: true } },
    { text: "Bin-based: 0-0.5, 0.5-0.7, 0.7-0.9, 0.9-1.0\nUpdated on each human review\nSegmented by category (30+ samples)\n", options: { fontSize: 10, fontFace: FONT_B, color: C.slate, breakLine: true } },
    { text: "Display:", options: { bold: true, fontSize: 12, fontFace: FONT_B, color: C.dark, breakLine: true } },
    { text: '"Confidence: 0.85 (calibrated: 0.73)"\nCalibrated < 0.5 = auto-flag for review', options: { fontSize: 10, fontFace: FONT_B, color: C.slate, breakLine: true } },
    { text: "", options: { breakLine: true, fontSize: 6 } },
    { text: "Confidence Decay:", options: { bold: true, fontSize: 12, fontFace: FONT_B, color: C.dark, breakLine: true } },
    { text: "base * 0.99^age_days * (1 + 0.1 * min(recall, 10))\nUsed often = stays high\nUnused = slowly decays\nWrong = actively penalized", options: { fontSize: 10, fontFace: FONT_B, color: C.slate } },
  ], { x: 5.7, y: 1.65, w: 3.2, h: 3.5 });
}

// ========== SLIDE 13: PHASE 3 OVERVIEW ==========
{
  const s = pres.addSlide();
  s.background = { color: C.lightBg };
  s.addText("Phase 3: Self-Evolution", { x: 0.8, y: 0.35, w: 8, h: 0.6, fontSize: 32, fontFace: FONT_H, color: C.navy, bold: true, margin: 0 });
  s.addText("2027  |  8 Tasks  |  System Gets Smarter Autonomously", { x: 0.8, y: 0.9, w: 8, h: 0.35, fontSize: 13, fontFace: FONT_B, color: C.purple, margin: 0 });

  const tasks = [
    { name: "SkillGapDetector", desc: "After RCA: detect capabilities the investigation needed but no skill covers.", risk: "High false positive rate" },
    { name: "SOPAutoWriter", desc: "Auto-generate draft skill from successful RCA investigation path.", risk: "Quality of generated SOPs" },
    { name: "Sandbox Replay", desc: "Validate draft skills by replaying past fault scenarios.", risk: "Cost of fault injection env" },
    { name: "Skill Expiration", desc: "Unused skills decay. Infra changes trigger re-validation.", risk: "Minimal" },
    { name: "Wisdom Maturation", desc: "Reinforce, contradict, merge, and retire wisdom entries.", risk: "LLM merge judgment quality" },
    { name: "Calibration by Category", desc: "Separate calibration per issue category (30+ samples needed).", risk: "Data volume requirement" },
    { name: "Self-Verification", desc: "Independent reasoning quality check before RCA output (16 failure types).", risk: "2x LLM cost per RCA" },
    { name: "Agent Skill Proposals", desc: "Agent suggests skill improvements after deviating from existing skill.", risk: "Minimal" },
  ];

  tasks.forEach((t, i) => {
    const col = i < 4 ? 0 : 1;
    const row = i % 4;
    const x = 0.5 + col * 4.7;
    const y = 1.5 + row * 0.95;
    s.addShape(pres.shapes.RECTANGLE, { x, y, w: 4.4, h: 0.8, fill: { color: C.white }, shadow: shadow() });
    s.addShape(pres.shapes.RECTANGLE, { x, y, w: 0.07, h: 0.8, fill: { color: C.purple } });
    s.addText(t.name, { x: x + 0.2, y: y + 0.03, w: 2.5, h: 0.3, fontSize: 12, fontFace: FONT_H, color: C.dark, bold: true, margin: 0 });
    s.addText(t.desc, { x: x + 0.2, y: y + 0.33, w: 4.0, h: 0.22, fontSize: 9, fontFace: FONT_B, color: C.slate, margin: 0 });
    s.addText(t.risk, { x: x + 0.2, y: y + 0.55, w: 4.0, h: 0.2, fontSize: 8, fontFace: FONT_B, color: C.amber, italic: true, margin: 0 });
  });

  s.addText("Each task requires A/B testing to prove ROI before production deployment", { x: 0.5, y: 5.15, w: 9, h: 0.3, fontSize: 11, fontFace: FONT_B, color: C.red, bold: true, margin: 0 });
}

// ========== SLIDE 14: PHASE 4 VISION ==========
{
  const s = pres.addSlide();
  s.background = { color: C.navy };
  s.addShape(pres.shapes.RECTANGLE, { x: 0, y: 0, w: 10, h: 0.06, fill: { color: C.cyan } });
  s.addText("Phase 4: Autonomous Operations", { x: 0.8, y: 0.3, w: 8, h: 0.6, fontSize: 32, fontFace: FONT_H, color: C.white, bold: true, margin: 0 });
  s.addText("2028+  |  7 Tasks  |  The Ultimate Vision", { x: 0.8, y: 0.85, w: 8, h: 0.35, fontSize: 13, fontFace: FONT_B, color: C.cyan, margin: 0 });

  const visions = [
    { name: "Cross-Service Correlation", desc: "N alerts from different services mapped to 1 root incident via Service Model + dependency graph." },
    { name: "Proactive Change Risk", desc: "Monitor deploy announcements in IM channels. Cross-reference with Wisdom: 'payment-service deploys have 30% incident rate.'" },
    { name: "Skill Generalization", desc: "Abstract specific skills into reusable templates. 'ECS OOM' + 'K8s OOM' = 'Container Memory Exhaustion' pattern." },
    { name: "Code Interpreter", desc: "Agent writes custom Python/SQL/PromQL queries for novel scenarios. Sandboxed execution." },
    { name: "Graduated Autonomy", desc: "Expand L-level boundaries as system proves reliability. L1 success > 95% for 3 months = propose L1 expansion." },
    { name: "Multi-Agent Verification", desc: "2-3 RCA agents independently analyze same incident. Consensus determines confidence." },
  ];

  visions.forEach((v, i) => {
    const col = i < 3 ? 0 : 1;
    const row = i % 3;
    const x = 0.5 + col * 4.7;
    const y = 1.5 + row * 1.25;
    s.addShape(pres.shapes.RECTANGLE, { x, y, w: 4.4, h: 1.05, fill: { color: "152E44" } });
    s.addShape(pres.shapes.RECTANGLE, { x, y, w: 0.07, h: 1.05, fill: { color: C.cyan } });
    s.addText(v.name, { x: x + 0.2, y: y + 0.05, w: 4.0, h: 0.35, fontSize: 13, fontFace: FONT_H, color: C.cyan, bold: true, margin: 0 });
    s.addText(v.desc, { x: x + 0.2, y: y + 0.4, w: 4.0, h: 0.55, fontSize: 10, fontFace: FONT_B, color: C.white, margin: 0 });
  });

  s.addText('"The goal: make every operator as effective as the best SRE — and eventually, better." — AIOpsLab Vision Paper', { x: 0.8, y: 5.0, w: 8, h: 0.4, fontSize: 10, fontFace: FONT_B, color: C.slate, italic: true, margin: 0 });
}

// ========== SLIDE 15: PRACTICAL VS THEORETICAL ==========
{
  const s = pres.addSlide();
  s.background = { color: C.lightBg };
  s.addText("Practical vs Theoretical Assessment", { x: 0.8, y: 0.35, w: 8, h: 0.6, fontSize: 28, fontFace: FONT_H, color: C.navy, bold: true, margin: 0 });
  s.addShape(pres.shapes.RECTANGLE, { x: 0.8, y: 0.9, w: 1.2, h: 0.04, fill: { color: C.teal } });

  const header = { fill: { color: C.navy }, color: C.white, bold: true, fontSize: 11, fontFace: FONT_B, align: "center", valign: "middle" };
  const cell = { fontSize: 10, fontFace: FONT_B, color: C.dark, valign: "middle" };

  const rows = [
    [
      { text: "Category", options: { ...header, align: "left" } },
      { text: "Components", options: header },
      { text: "Tasks", options: header },
      { text: "Risk Level", options: header },
      { text: "Market Demand", options: header },
    ],
    [{ text: "Immediate + Market Need", options: { ...cell, bold: true, color: C.green } }, { text: "Connectors, Service Model,\nEvidence, PostAction, Review", options: cell }, { text: "28", options: { ...cell, align: "center", bold: true } }, { text: "LOW", options: { ...cell, align: "center", color: C.green, bold: true } }, { text: "HIGH", options: { ...cell, align: "center", color: C.green, bold: true } }],
    [{ text: "Short-term + Data-Dependent", options: { ...cell, bold: true, color: C.amber } }, { text: "Prompt Engine, Wisdom,\nCalibration, Memory", options: cell }, { text: "12", options: { ...cell, align: "center", bold: true } }, { text: "MEDIUM", options: { ...cell, align: "center", color: C.amber, bold: true } }, { text: "MEDIUM", options: { ...cell, align: "center", color: C.amber, bold: true } }],
    [{ text: "Theoretical + Needs Proof", options: { ...cell, bold: true, color: C.orange } }, { text: "SkillGap, SOPWriter,\nSandbox, Self-Verify", options: cell }, { text: "8", options: { ...cell, align: "center", bold: true } }, { text: "HIGH", options: { ...cell, align: "center", color: C.red, bold: true } }, { text: "LOW", options: { ...cell, align: "center", color: C.amber, bold: true } }],
    [{ text: "Vision + Far Future", options: { ...cell, bold: true, color: C.slate } }, { text: "Cross-Service, Proactive,\nMulti-Agent, Code Interpreter", options: cell }, { text: "7", options: { ...cell, align: "center", bold: true } }, { text: "UNKNOWN", options: { ...cell, align: "center", color: C.slate, bold: true } }, { text: "HIGH (future)", options: { ...cell, align: "center", color: C.slate, bold: true } }],
  ];

  s.addTable(rows, {
    x: 0.5, y: 1.2, w: 9.0,
    colW: [2.2, 2.5, 0.8, 1.5, 2.0],
    border: { pt: 0.5, color: C.divider },
    rowH: [0.45, 0.65, 0.65, 0.65, 0.65],
    autoPage: false,
  });

  // Key insight box
  s.addShape(pres.shapes.RECTANGLE, { x: 0.5, y: 4.2, w: 9.0, h: 1.1, fill: { color: C.white }, shadow: shadow() });
  s.addShape(pres.shapes.RECTANGLE, { x: 0.5, y: 4.2, w: 0.07, h: 1.1, fill: { color: C.teal } });
  s.addText("Strategic Principle", { x: 0.75, y: 4.25, w: 8.5, h: 0.3, fontSize: 14, fontFace: FONT_H, color: C.teal, bold: true, margin: 0 });
  s.addText("Phase 1 + Phase 2 front half = Product (solves real pain, competitive moat)\nPhase 2 back half = Flywheel (needs data accumulation to prove value)\nPhase 3 = Research (each task needs A/B test before production)\nPhase 4 = Vision (directional guide, not commitment)", { x: 0.75, y: 4.55, w: 8.5, h: 0.7, fontSize: 11, fontFace: FONT_B, color: C.dark, margin: 0 });
}

// ========== SLIDE 16: SHORT-TERM PRIORITY ==========
{
  const s = pres.addSlide();
  s.background = { color: C.lightBg };
  s.addText("Short-Term Priority: 28 Tasks", { x: 0.8, y: 0.35, w: 8, h: 0.6, fontSize: 28, fontFace: FONT_H, color: C.navy, bold: true, margin: 0 });
  s.addText("Phase 1 (all 21) + Phase 2 PostActionValidator (3) + Phase 2 Human Review (4)", { x: 0.8, y: 0.9, w: 8, h: 0.3, fontSize: 12, fontFace: FONT_B, color: C.teal, margin: 0 });

  // Why these 28?
  s.addShape(pres.shapes.RECTANGLE, { x: 0.5, y: 1.4, w: 9.0, h: 3.8, fill: { color: C.white }, shadow: shadow() });

  const reasons = [
    { label: "Connectors", why: "Let Agent query external systems. Without this, Agent is blind.", demand: "Tool fragmentation is SRE's #1 complaint" },
    { label: "Service Model", why: "Know which service is affected, who owns it, what depends on it.", demand: "No existing tool provides service-level AIOps view" },
    { label: "Evidence Weighting", why: "Make RCA results explainable. CloudTrail proof vs pure guess.", demand: "Trust is the #1 barrier to AIOps adoption" },
    { label: "Alert Classification", why: "Route to correct strategy. Reuse historical experience.", demand: "Alert fatigue is universal SRE problem" },
    { label: "PostActionValidator", why: "Automated verify: did the fix actually work? No more staring at dashboards.", demand: "Post-fix verification is 100% manual today" },
    { label: "Human Review", why: "One button = Ground Truth. Foundation for ALL future learning.", demand: "Enables the entire self-improvement flywheel" },
  ];

  reasons.forEach((r, i) => {
    const y = 1.55 + i * 0.58;
    s.addShape(pres.shapes.RECTANGLE, { x: 0.65, y, w: 0.07, h: 0.45, fill: { color: C.teal } });
    s.addText(r.label, { x: 0.9, y, w: 1.5, h: 0.45, fontSize: 12, fontFace: FONT_H, color: C.dark, bold: true, valign: "middle", margin: 0 });
    s.addText(r.why, { x: 2.5, y, w: 3.2, h: 0.45, fontSize: 10, fontFace: FONT_B, color: C.dark, valign: "middle", margin: 0 });
    s.addText(r.demand, { x: 5.8, y, w: 3.5, h: 0.45, fontSize: 10, fontFace: FONT_B, color: C.teal, italic: true, valign: "middle", margin: 0 });
  });

  // Headers
  s.addText("Component", { x: 0.9, y: 1.3, w: 1.5, h: 0.25, fontSize: 9, fontFace: FONT_B, color: C.slate, bold: true, margin: 0 });
  s.addText("Why Essential", { x: 2.5, y: 1.3, w: 3.2, h: 0.25, fontSize: 9, fontFace: FONT_B, color: C.slate, bold: true, margin: 0 });
  s.addText("Market Signal", { x: 5.8, y: 1.3, w: 3.5, h: 0.25, fontSize: 9, fontFace: FONT_B, color: C.slate, bold: true, margin: 0 });
}

// ========== SLIDE 17: RISK ASSESSMENT ==========
{
  const s = pres.addSlide();
  s.background = { color: C.lightBg };
  s.addText("Risk Assessment & Mitigation", { x: 0.8, y: 0.35, w: 8, h: 0.6, fontSize: 28, fontFace: FONT_H, color: C.navy, bold: true, margin: 0 });
  s.addShape(pres.shapes.RECTANGLE, { x: 0.8, y: 0.9, w: 1.2, h: 0.04, fill: { color: C.teal } });

  const risks = [
    { risk: "Cold Start Problem", desc: "First 20 cases have no historical data for Prompt Engine. Few-shot retriever returns empty.", mitigation: "Default strategies per category. Keyword classification as fast path. Value grows with each case.", severity: "MEDIUM", color: C.amber },
    { risk: "Data Volume for Calibration", desc: "Confidence calibration needs 30+ reviews per bin. May take 3-6 months.", mitigation: "Return raw confidence until bins fill. Display 'uncalibrated' indicator. Calibrate 'all' bin first.", severity: "LOW", color: C.green },
    { risk: "Wisdom Sparsity", desc: "If environment is too diverse, each pattern appears only 1-2 times. Wisdom can't crystallize.", mitigation: "Broader categories ('compute' vs 'ECS OOM'). Accept that Wisdom is supplementary, not required.", severity: "MEDIUM", color: C.amber },
    { risk: "Sandbox Replay Cost (Phase 3)", desc: "Fault injection environment = significant infra cost. Production env impossible to test.", mitigation: "Use KB case replay instead of live fault injection. Validate against known Ground Truth.", severity: "HIGH", color: C.red },
    { risk: "Self-Verification LLM Cost", desc: "Double LLM call per RCA. At scale, significant token cost.", mitigation: "Only trigger for high-severity or low-confidence RCAs. Human review may be more cost-effective.", severity: "HIGH", color: C.red },
    { risk: "SkillGapDetector False Positives", desc: "Agent didn't use a skill != skill is missing. 'Gap' definition is ambiguous.", mitigation: "Let humans declare gaps instead. Or require 3+ consistent gaps before triggering SOPWriter.", severity: "HIGH", color: C.red },
  ];

  risks.forEach((r, i) => {
    const col = i < 3 ? 0 : 1;
    const row = i % 3;
    const x = 0.5 + col * 4.7;
    const y = 1.2 + row * 1.35;
    s.addShape(pres.shapes.RECTANGLE, { x, y, w: 4.4, h: 1.2, fill: { color: C.white }, shadow: shadow() });
    s.addShape(pres.shapes.RECTANGLE, { x, y, w: 0.07, h: 1.2, fill: { color: r.color } });
    s.addText(r.risk, { x: x + 0.2, y: y + 0.03, w: 3.3, h: 0.3, fontSize: 12, fontFace: FONT_H, color: C.dark, bold: true, margin: 0 });
    s.addText(r.severity, { x: x + 3.5, y: y + 0.05, w: 0.7, h: 0.25, fontSize: 8, fontFace: FONT_B, color: r.color, bold: true, align: "center", margin: 0 });
    s.addText(r.desc, { x: x + 0.2, y: y + 0.33, w: 4.0, h: 0.3, fontSize: 9, fontFace: FONT_B, color: C.slate, margin: 0 });
    s.addText(r.mitigation, { x: x + 0.2, y: y + 0.7, w: 4.0, h: 0.4, fontSize: 9, fontFace: FONT_B, color: C.green, margin: 0 });
  });
}

// ========== SLIDE 18: LEARNING FLYWHEEL ==========
{
  const s = pres.addSlide();
  s.background = { color: C.navy };
  s.addShape(pres.shapes.RECTANGLE, { x: 0, y: 0, w: 10, h: 0.06, fill: { color: C.cyan } });
  s.addText("The Learning Flywheel", { x: 0.8, y: 0.3, w: 8, h: 0.6, fontSize: 32, fontFace: FONT_H, color: C.white, bold: true, margin: 0 });

  const steps = [
    { name: "Phase 1", desc: "Agent investigates\nwith tools + evidence", x: 1.0, y: 1.4 },
    { name: "Phase 2", desc: "Human reviews create\nGround Truth data", x: 4.0, y: 1.4 },
    { name: "Phase 2b", desc: "Calibration + Wisdom\nimprove future prompts", x: 7.0, y: 1.4 },
    { name: "Phase 3", desc: "System auto-generates\nand validates skills", x: 7.0, y: 3.2 },
    { name: "Phase 4", desc: "Proactive detection\n+ graduated autonomy", x: 4.0, y: 3.2 },
    { name: "Outcome", desc: "Each cycle makes the\nnext faster + more accurate", x: 1.0, y: 3.2 },
  ];

  steps.forEach((st, i) => {
    s.addShape(pres.shapes.RECTANGLE, { x: st.x, y: st.y, w: 2.2, h: 1.2, fill: { color: "152E44" } });
    s.addShape(pres.shapes.RECTANGLE, { x: st.x, y: st.y, w: 2.2, h: 0.35, fill: { color: i < 5 ? C.teal : C.green } });
    s.addText(st.name, { x: st.x, y: st.y + 0.02, w: 2.2, h: 0.3, fontSize: 12, fontFace: FONT_H, color: C.white, bold: true, align: "center", margin: 0 });
    s.addText(st.desc, { x: st.x + 0.12, y: st.y + 0.4, w: 2.0, h: 0.7, fontSize: 10, fontFace: FONT_B, color: C.white, margin: 0 });
  });

  // Arrows (text-based)
  s.addText(">", { x: 3.2, y: 1.75, w: 0.8, h: 0.4, fontSize: 24, fontFace: FONT_B, color: C.cyan, align: "center", valign: "middle", margin: 0 });
  s.addText(">", { x: 6.2, y: 1.75, w: 0.8, h: 0.4, fontSize: 24, fontFace: FONT_B, color: C.cyan, align: "center", valign: "middle", margin: 0 });
  s.addText("v", { x: 7.9, y: 2.6, w: 0.4, h: 0.6, fontSize: 20, fontFace: FONT_B, color: C.cyan, align: "center", valign: "middle", margin: 0 });
  s.addText("<", { x: 6.2, y: 3.55, w: 0.8, h: 0.4, fontSize: 24, fontFace: FONT_B, color: C.cyan, align: "center", valign: "middle", margin: 0 });
  s.addText("<", { x: 3.2, y: 3.55, w: 0.8, h: 0.4, fontSize: 24, fontFace: FONT_B, color: C.cyan, align: "center", valign: "middle", margin: 0 });

  s.addText("Incident #1: 25 min (manual investigation)", { x: 0.8, y: 4.7, w: 8, h: 0.3, fontSize: 14, fontFace: FONT_B, color: C.slate, margin: 0 });
  s.addText("Incident #2 (similar): 3 min (Memory Fast Path + Wisdom)", { x: 0.8, y: 5.0, w: 8, h: 0.3, fontSize: 14, fontFace: FONT_B, color: C.cyan, bold: true, margin: 0 });
}

// ========== SLIDE 19: SUCCESS METRICS ==========
{
  const s = pres.addSlide();
  s.background = { color: C.lightBg };
  s.addText("Success Metrics", { x: 0.8, y: 0.35, w: 8, h: 0.6, fontSize: 32, fontFace: FONT_H, color: C.navy, bold: true, margin: 0 });
  s.addShape(pres.shapes.RECTANGLE, { x: 0.8, y: 0.95, w: 1.2, h: 0.04, fill: { color: C.teal } });

  const header = { fill: { color: C.navy }, color: C.white, bold: true, fontSize: 11, fontFace: FONT_B, align: "center", valign: "middle" };
  const cell = { fontSize: 10, fontFace: FONT_B, color: C.dark, valign: "middle" };

  const rows = [
    [
      { text: "Metric", options: { ...header, align: "left" } },
      { text: "Current\n(MVP 1.0)", options: header },
      { text: "Target\n(Next-Gen 2.0)", options: header },
      { text: "How Measured", options: header },
    ],
    [{ text: "RCA accuracy (human-verified)", options: cell }, { text: "Unknown", options: { ...cell, align: "center" } }, { text: "> 80%", options: { ...cell, align: "center", color: C.green, bold: true } }, { text: "ReviewFeedback verdicts", options: cell }],
    [{ text: "RCA time (known patterns)", options: cell }, { text: "2-6 min", options: { ...cell, align: "center" } }, { text: "< 2 min", options: { ...cell, align: "center", color: C.green, bold: true } }, { text: "Pipeline timestamps", options: cell }],
    [{ text: "PostAction SUCCESS rate", options: cell }, { text: "N/A", options: { ...cell, align: "center" } }, { text: "> 70%", options: { ...cell, align: "center", color: C.green, bold: true } }, { text: "PostActionResult", options: cell }],
    [{ text: "KB verified case ratio", options: cell }, { text: "0%", options: { ...cell, align: "center" } }, { text: "> 50%", options: { ...cell, align: "center", color: C.green, bold: true } }, { text: "Review data (6 months)", options: cell }],
    [{ text: "Confidence calibration error", options: cell }, { text: "Unknown", options: { ...cell, align: "center" } }, { text: "< 10%", options: { ...cell, align: "center", color: C.green, bold: true } }, { text: "Calibration vs actuals", options: cell }],
    [{ text: "Wisdom Roadmap coverage", options: cell }, { text: "0 entries", options: { ...cell, align: "center" } }, { text: "> 40 patterns", options: { ...cell, align: "center", color: C.green, bold: true } }, { text: "KB count (6 months)", options: cell }],
    [{ text: "Service model coverage", options: cell }, { text: "0%", options: { ...cell, align: "center" } }, { text: "> 80%", options: { ...cell, align: "center", color: C.green, bold: true } }, { text: "DB service entries", options: cell }],
    [{ text: "Evidence-backed RCA ratio", options: cell }, { text: "Unknown", options: { ...cell, align: "center" } }, { text: "> 90%", options: { ...cell, align: "center", color: C.green, bold: true } }, { text: "Evidence chain analysis", options: cell }],
  ];

  s.addTable(rows, {
    x: 0.5, y: 1.15, w: 9.0,
    colW: [2.8, 1.3, 1.5, 3.4],
    border: { pt: 0.5, color: C.divider },
    rowH: [0.45, 0.42, 0.42, 0.42, 0.42, 0.42, 0.42, 0.42, 0.42],
    autoPage: false,
  });
}

// ========== SLIDE 20: END-TO-END SCENARIO ==========
{
  const s = pres.addSlide();
  s.background = { color: C.lightBg };
  s.addText("End-to-End Scenario: Payment API Alert", { x: 0.8, y: 0.35, w: 8, h: 0.6, fontSize: 28, fontFace: FONT_H, color: C.navy, bold: true, margin: 0 });
  s.addShape(pres.shapes.RECTANGLE, { x: 0.8, y: 0.9, w: 1.2, h: 0.04, fill: { color: C.teal } });

  const timeline = [
    { time: "10:35", phase: "PERCEIVE", detail: "Slack alert: payment-api HealthCheckFailures\nClassified: cache, pattern: cache_memory_exhaustion\n3 similar KB cases found, Redis shared with order-service", color: C.teal },
    { time: "10:35", phase: "PLAN", detail: "Wisdom: 'check deployments first' (85% success)\nFew-shot: case-42 attached (Redis OOM after deploy)\nOptimized prompt: 2800 tokens", color: "0E7490" },
    { time: "10:36", phase: "ACT", detail: "CloudTrail: v24 deployed 10:30 [0.95]\nDatadog: Redis memory spike at 10:30 [0.80]\nGitHub: v24 = promo:* cache, no TTL [0.90]", color: C.cyan },
    { time: "10:37", phase: "DECIDE", detail: "RCA: v24 promo:* keys no TTL, Redis exhaustion\nCascade: order-service via shared Redis\nConfidence: 0.88 (calibrated: 0.76)", color: C.mint },
    { time: "10:37", phase: "VERIFY", detail: "Fix: TTL + rollback (L1, auto-approved)\nT0: OK, T1: Redis dropping, T2: healthcheck pass\nT3: no new alerts = SUCCESS", color: C.green },
    { time: "10:38", phase: "LEARN", detail: "Episodic: case-142 saved\nWisdom: 'cache_memory_exhaustion' reinforced\nTotal: 3 min. Next similar: ~1.5 min", color: "047857" },
  ];

  timeline.forEach((t, i) => {
    const col = i < 3 ? 0 : 1;
    const row = i % 3;
    const x = 0.5 + col * 4.7;
    const y = 1.15 + row * 1.35;
    s.addShape(pres.shapes.RECTANGLE, { x, y, w: 4.4, h: 1.2, fill: { color: C.white }, shadow: shadow() });
    s.addShape(pres.shapes.RECTANGLE, { x, y, w: 0.07, h: 1.2, fill: { color: t.color } });
    s.addText(`${t.time}  ${t.phase}`, { x: x + 0.2, y: y + 0.03, w: 4.0, h: 0.3, fontSize: 12, fontFace: FONT_H, color: t.color, bold: true, margin: 0 });
    s.addText(t.detail, { x: x + 0.2, y: y + 0.33, w: 4.0, h: 0.8, fontSize: 9, fontFace: FONT_B, color: C.dark, margin: 0 });
  });

  s.addText("3 minutes total. Every incident makes the next one faster.", { x: 0.5, y: 5.15, w: 9, h: 0.3, fontSize: 12, fontFace: FONT_B, color: C.teal, bold: true, margin: 0 });
}

// ========== SLIDE 21: ACADEMIC FOUNDATION ==========
{
  const s = pres.addSlide();
  s.background = { color: C.lightBg };
  s.addText("Academic Foundation", { x: 0.8, y: 0.35, w: 8, h: 0.6, fontSize: 28, fontFace: FONT_H, color: C.navy, bold: true, margin: 0 });
  s.addText("11 Papers  |  180,000+ Real Incidents  |  Production-Proven Patterns", { x: 0.8, y: 0.9, w: 8, h: 0.3, fontSize: 12, fontFace: FONT_B, color: C.teal, margin: 0 });

  const header = { fill: { color: C.navy }, color: C.white, bold: true, fontSize: 10, fontFace: FONT_B, valign: "middle" };
  const cell = { fontSize: 9, fontFace: FONT_B, color: C.dark, valign: "middle" };

  const rows = [
    [{ text: "#", options: { ...header, align: "center" } }, { text: "Paper", options: header }, { text: "ArXiv", options: { ...header, align: "center" } }, { text: "Key Contribution", options: header }],
    [{ text: "1", options: { ...cell, align: "center" } }, { text: "eARCO (Microsoft)", options: { ...cell, bold: true } }, { text: "2504.11505", options: { ...cell, align: "center" } }, { text: "Prompt > RAG > Fine-tuning, +21% accuracy", options: cell }],
    [{ text: "2", options: { ...cell, align: "center" } }, { text: "Why AI Agents Fail at Cloud RCA", options: { ...cell, bold: true } }, { text: "2602.09937", options: { ...cell, align: "center" } }, { text: "12 failure types, architecture > prompts", options: cell }],
    [{ text: "3", options: { ...cell, align: "center" } }, { text: "16 RCA Reasoning Failures", options: { ...cell, bold: true } }, { text: "2601.22208", options: { ...cell, align: "center" } }, { text: "Multi-hop reasoning is the hardest failure", options: cell }],
    [{ text: "4", options: { ...cell, align: "center" } }, { text: "AIOpsLab (Microsoft)", options: { ...cell, bold: true } }, { text: "2501.06706", options: { ...cell, align: "center" } }, { text: "Holistic AIOps evaluation framework", options: cell }],
    [{ text: "5", options: { ...cell, align: "center" } }, { text: "OpsAgent: Self-Evolution", options: { ...cell, bold: true } }, { text: "2510.24145", options: { ...cell, align: "center" } }, { text: "Dual self-evolution mechanism", options: cell }],
    [{ text: "6", options: { ...cell, align: "center" } }, { text: "CCAR: Safe Resolution", options: { ...cell, bold: true } }, { text: "2603.08736", options: { ...cell, align: "center" } }, { text: "Formal false-positive bounds for safe remediation", options: cell }],
    [{ text: "7", options: { ...cell, align: "center" } }, { text: "RCACopilot (Microsoft)", options: { ...cell, bold: true } }, { text: "2305.15778", options: { ...cell, align: "center" } }, { text: "4-year production RCA, 0.766 accuracy baseline", options: cell }],
    [{ text: "8", options: { ...cell, align: "center" } }, { text: "mABC: Multi-Agent RCA", options: { ...cell, bold: true } }, { text: "2404.12135", options: { ...cell, align: "center" } }, { text: "Blockchain consensus for RCA verification", options: cell }],
  ];

  s.addTable(rows, {
    x: 0.5, y: 1.3, w: 9.0,
    colW: [0.5, 2.5, 1.2, 4.8],
    border: { pt: 0.5, color: C.divider },
    rowH: [0.4, 0.4, 0.4, 0.4, 0.4, 0.4, 0.4, 0.4, 0.4],
    autoPage: false,
  });
}

// ========== SLIDE 22: CONCLUSION ==========
{
  const s = pres.addSlide();
  s.background = { color: C.navy };
  s.addShape(pres.shapes.RECTANGLE, { x: 0, y: 0, w: 10, h: 0.06, fill: { color: C.cyan } });
  s.addText("Conclusion & Next Steps", { x: 0.8, y: 0.3, w: 8, h: 0.6, fontSize: 32, fontFace: FONT_H, color: C.white, bold: true, margin: 0 });

  // 3 key takeaways
  const takeaways = [
    { num: "01", title: "Product (Phase 1 + 2 front)", desc: "28 tasks that solve real SRE pain points.\nConnectors + Evidence + Service Model + PostAction + Human Review.\nComplete 'investigate > fix > verify > learn' closed loop." },
    { num: "02", title: "Flywheel (Phase 2 back)", desc: "12 tasks that need data to prove value.\nWisdom + Calibration + Memory = system gets smarter.\nMonitor data accumulation speed before heavy investment." },
    { num: "03", title: "Research (Phase 3-4)", desc: "15 tasks that are directionally correct but unproven.\nEach requires A/B testing before production.\nVision guides architecture, not implementation schedule." },
  ];

  takeaways.forEach((t, i) => {
    const y = 1.2 + i * 1.2;
    s.addShape(pres.shapes.RECTANGLE, { x: 0.5, y, w: 9.0, h: 1.0, fill: { color: "152E44" } });
    s.addShape(pres.shapes.RECTANGLE, { x: 0.5, y, w: 0.07, h: 1.0, fill: { color: C.cyan } });
    s.addText(t.num, { x: 0.8, y, w: 0.6, h: 1.0, fontSize: 28, fontFace: FONT_H, color: C.cyan, bold: true, valign: "middle", margin: 0 });
    s.addText(t.title, { x: 1.5, y: y + 0.05, w: 3.0, h: 0.35, fontSize: 16, fontFace: FONT_H, color: C.white, bold: true, margin: 0 });
    s.addText(t.desc, { x: 1.5, y: y + 0.4, w: 7.8, h: 0.55, fontSize: 11, fontFace: FONT_B, color: C.white, margin: 0 });
  });

  // Next steps
  s.addText("Immediate Next Steps", { x: 0.8, y: 4.8, w: 4, h: 0.35, fontSize: 16, fontFace: FONT_H, color: C.cyan, bold: true, margin: 0 });
  s.addText([
    { text: "1. Begin Phase 1 implementation (4 parallel tracks)", options: { fontSize: 12, fontFace: FONT_B, color: C.white, breakLine: true } },
    { text: "2. Set up connectors.yaml for target environment", options: { fontSize: 12, fontFace: FONT_B, color: C.white, breakLine: true } },
    { text: "3. Deploy Human Review UI as early as possible to start Ground Truth collection", options: { fontSize: 12, fontFace: FONT_B, color: C.white } },
  ], { x: 0.8, y: 5.1, w: 9, h: 0.5 });
}

// ========== WRITE FILE ==========
const outPath = "/Users/malibo/MyDev/AgenticOps/docs/superpowers/plans/AgenticOps-Next-Gen-Strategic-Roadmap.pptx";
pres.writeFile({ fileName: outPath }).then(() => {
  console.log("PPTX created: " + outPath);
}).catch(err => {
  console.error("Error:", err);
});
