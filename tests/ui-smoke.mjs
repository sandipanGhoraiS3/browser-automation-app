import { chromium } from 'playwright';
import assert from 'node:assert/strict';
import fs from 'node:fs';
const executablePath = process.env.BROWSER_EXECUTABLE_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const browser = await chromium.launch({ executablePath, headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const errors = [];
page.on('pageerror', error => errors.push(error.message));
try {
  await page.goto('http://127.0.0.1:5173');
  await page.getByRole('heading', { name: 'A little direction.' }).waitFor();
  await page.getByRole('button', { name: 'Settings', exact: true }).click();
  await page.getByRole('dialog').waitFor();
  await page.getByRole('button', { name: 'Back to workspace' }).click();
  fs.mkdirSync('data/test-artifacts', { recursive: true });
  await page.screenshot({ path: 'data/test-artifacts/desktop.png', fullPage: true });
  await page.locator('.new-chat').click();
  await page.getByText('Session connected', { exact: false }).waitFor({ timeout: 30000 });
  await page.getByAltText('Latest real browser screenshot').waitFor();
  await page.getByLabel('Message Orbit').fill('close browser');
  await page.getByRole('button', { name: 'Send message', exact: true }).click();
  await page.getByText('Browser closed. Your conversation is saved.', { exact: true }).waitFor({ timeout: 15000 });
  await page.reload();
  // Conversation history remains available after reload.
  await page.getByRole('button', { name: 'close browser', exact: true }).click();
  await page.getByText('Browser closed. Your conversation is saved.', { exact: true }).waitFor();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: 'data/test-artifacts/mobile.png', fullPage: true });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, 'Mobile horizontal overflow');
  assert.deepEqual(errors, []);
  console.log('PASS: UI load, settings, create real browser session, live screenshot, WebSocket chat, explicit browser close, persisted history, mobile layout');
} finally { await browser.close(); }
