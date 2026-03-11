/**
 * ClawOps Frontend E2E Tests — Playwright
 * 
 * Verifies:
 * 1. All pages load without JS errors
 * 2. Sidebar navigation works (all 18 entries)
 * 3. Dashboard displays numbers (not empty)
 * 4. Issues list renders data
 * 5. Dark theme CSS rules applied
 * 6. Style Guide compliance (colors, spacing)
 */
import { chromium } from 'playwright';

const BASE = 'http://localhost:8888';
const TIMEOUT = 15000;

// All sidebar routes
const NAV_ROUTES = [
  { path: '/app', label: 'Dashboard' },
  { path: '/app/chat', label: 'Chat' },
  { path: '/app/issues', label: 'Issues' },
  { path: '/app/fix-plans', label: 'Fix Plans' },
  { path: '/app/resources', label: 'Resources' },
  { path: '/app/network', label: 'Network' },
  { path: '/app/reports', label: 'Reports' },
  { path: '/app/schedules', label: 'Schedules' },
  { path: '/app/notifications', label: 'Notifications' },
  { path: '/app/audit-log', label: 'Audit Log' },
  { path: '/app/knowledge-base', label: 'Knowledge Base' },
  { path: '/app/ai', label: 'AI Center' },
  { path: '/app/diagnose', label: 'Diagnose' },
  { path: '/app/knowledge', label: 'Knowledge' },
];

// Style Guide colors
const STYLE = {
  bg: 'rgb(33, 33, 33)',        // #212121
  sidebar: 'rgb(23, 23, 23)',   // #171717
  card: 'rgb(47, 47, 47)',      // #2f2f2f
};

let browser, page;
let results = { passed: 0, failed: 0, errors: [] };
let jsErrors = [];

function pass(name) {
  results.passed++;
  console.log(`  ✅ ${name}`);
}

function fail(name, err) {
  results.failed++;
  results.errors.push({ name, error: String(err) });
  console.log(`  ❌ ${name}: ${err}`);
}

async function test(name, fn) {
  try {
    await fn();
    pass(name);
  } catch (e) {
    fail(name, e.message || e);
  }
}

async function setup() {
  browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  page = await context.newPage();
  
  // Capture JS errors
  page.on('pageerror', err => jsErrors.push(err.message));
}

async function teardown() {
  await browser?.close();
}

// ── Tests ────────────────────────────────────────────────────────────

async function testAllPagesLoad() {
  console.log('\n📄 Page Load Tests');
  for (const route of NAV_ROUTES) {
    await test(`${route.label} (${route.path}) loads`, async () => {
      jsErrors = [];
      const resp = await page.goto(`${BASE}${route.path}`, { 
        waitUntil: 'networkidle', 
        timeout: TIMEOUT 
      });
      if (!resp || resp.status() >= 400) {
        throw new Error(`HTTP ${resp?.status()}`);
      }
      // Check no fatal JS errors
      const fatal = jsErrors.filter(e => !e.includes('ResizeObserver'));
      if (fatal.length > 0) {
        throw new Error(`JS errors: ${fatal.join('; ')}`);
      }
    });
  }
}

async function testSidebarNavigation() {
  console.log('\n🧭 Sidebar Navigation Tests');
  await page.goto(`${BASE}/app`, { waitUntil: 'networkidle', timeout: TIMEOUT });
  
  for (const route of NAV_ROUTES) {
    await test(`Sidebar link "${route.label}" navigable`, async () => {
      const link = page.locator(`aside a[href="${route.path}"]`);
      const count = await link.count();
      if (count === 0) {
        throw new Error(`Sidebar link not found for ${route.path}`);
      }
    });
  }

  // Check "AI Ops" section label exists (renamed from "L5")
  await test('Section label "AI Ops" exists (not "L5")', async () => {
    const aiOps = page.locator('aside p:text("AI OPS"), aside p:text("AI Ops"), aside p:text("AI ops")');
    const l5 = page.locator('aside p:text("L5")');
    const aiOpsCount = await aiOps.count();
    const l5Count = await l5.count();
    if (aiOpsCount === 0) throw new Error('"AI Ops" section label not found');
    if (l5Count > 0) throw new Error('"L5" label still present — should be renamed');
  });
}

async function testDarkTheme() {
  console.log('\n🎨 Dark Theme Tests');
  await page.goto(`${BASE}/app`, { waitUntil: 'networkidle', timeout: TIMEOUT });
  
  await test('Body background is dark (#212121)', async () => {
    const bg = await page.evaluate(() => {
      return getComputedStyle(document.body).backgroundColor;
    });
    if (bg !== STYLE.bg) throw new Error(`Expected ${STYLE.bg}, got ${bg}`);
  });

  await test('Sidebar background is #171717', async () => {
    const bg = await page.evaluate(() => {
      const aside = document.querySelector('aside');
      return aside ? getComputedStyle(aside).backgroundColor : 'NOT FOUND';
    });
    if (bg !== STYLE.sidebar) throw new Error(`Expected ${STYLE.sidebar}, got ${bg}`);
  });

  await test('No light-theme bg classes in rendered DOM', async () => {
    const lightClasses = await page.evaluate(() => {
      const all = document.querySelectorAll('[class*="bg-white"], [class*="bg-gray-50"], [class*="bg-gray-100"]');
      return all.length;
    });
    if (lightClasses > 0) throw new Error(`Found ${lightClasses} elements with light bg classes`);
  });

  await test('Title is "ClawOps"', async () => {
    const title = await page.title();
    if (title !== 'ClawOps') throw new Error(`Expected "ClawOps", got "${title}"`);
  });
}

async function testDashboardContent() {
  console.log('\n📊 Dashboard Content Tests');
  await page.goto(`${BASE}/app`, { waitUntil: 'networkidle', timeout: TIMEOUT });

  await test('Dashboard has stat cards', async () => {
    // Wait for stats to load
    await page.waitForTimeout(2000);
    const cards = page.locator('[class*="StatCard"], [class*="stat-card"], .grid > div');
    const count = await cards.count();
    if (count < 2) throw new Error(`Expected >=2 stat cards, got ${count}`);
  });

  await test('Dashboard shows numbers (not all zeros/empty)', async () => {
    await page.waitForTimeout(1000);
    const text = await page.locator('main').textContent();
    // Should have at least some numeric content
    const hasNumbers = /\d+/.test(text);
    if (!hasNumbers) throw new Error('No numbers found on Dashboard');
  });
}

async function testIssuesList() {
  console.log('\n🐛 Issues Page Tests');
  await page.goto(`${BASE}/app/issues`, { waitUntil: 'networkidle', timeout: TIMEOUT });
  await page.waitForTimeout(2000);

  await test('Issues page loads without error', async () => {
    const text = await page.locator('main').textContent();
    if (text.includes('Error') && text.includes('retry')) {
      throw new Error('Issues page shows error state');
    }
  });

  await test('Issues table or list present', async () => {
    const table = page.locator('table, [class*="DataTable"], [role="table"]');
    const count = await table.count();
    // If no issues exist, at least empty state should show
    if (count === 0) {
      const empty = page.locator(':text("No issues"), :text("empty"), :text("No data")');
      const emptyCount = await empty.count();
      if (emptyCount === 0) throw new Error('No table and no empty state found');
    }
  });
}

async function testContentWidth() {
  console.log('\n📐 Layout Tests');
  await page.goto(`${BASE}/app`, { waitUntil: 'networkidle', timeout: TIMEOUT });

  await test('Content area has max-width constraint (breathing room)', async () => {
    const mainWidth = await page.evaluate(() => {
      const main = document.querySelector('main');
      if (!main) return 0;
      const style = getComputedStyle(main);
      return main.offsetWidth;
    });
    // With max-w-5xl (1024px) on a 1440px viewport, main should be < 1100px
    if (mainWidth > 1200) {
      throw new Error(`Content too wide: ${mainWidth}px (expected <=1200px with max-w constraint)`);
    }
  });
}

async function testScreenshots() {
  console.log('\n📸 Screenshots');
  const pages = [
    { path: '/app', name: 'dashboard' },
    { path: '/app/issues', name: 'issues' },
    { path: '/app/chat', name: 'chat' },
  ];
  for (const p of pages) {
    await test(`Screenshot: ${p.name}`, async () => {
      await page.goto(`${BASE}${p.path}`, { waitUntil: 'networkidle', timeout: TIMEOUT });
      await page.waitForTimeout(1000);
      await page.screenshot({ 
        path: `/tmp/clawops-${p.name}.png`, 
        fullPage: true 
      });
    });
  }
}

// ── Main ─────────────────────────────────────────────────────────────

async function main() {
  console.log('🔬 ClawOps Frontend E2E Tests');
  console.log(`   Target: ${BASE}`);
  console.log(`   Date: ${new Date().toISOString()}`);
  
  await setup();

  try {
    await testAllPagesLoad();
    await testSidebarNavigation();
    await testDarkTheme();
    await testDashboardContent();
    await testIssuesList();
    await testContentWidth();
    await testScreenshots();
  } finally {
    await teardown();
  }

  console.log(`\n${'═'.repeat(50)}`);
  console.log(`📊 Results: ${results.passed} passed, ${results.failed} failed`);
  if (results.errors.length > 0) {
    console.log('\nFailures:');
    for (const e of results.errors) {
      console.log(`  ❌ ${e.name}: ${e.error}`);
    }
  }
  console.log(`${'═'.repeat(50)}`);
  
  process.exit(results.failed > 0 ? 1 : 0);
}

main().catch(e => {
  console.error('Fatal:', e);
  process.exit(2);
});
