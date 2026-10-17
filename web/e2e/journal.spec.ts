import { test, expect } from '@playwright/test';

test('map evidence, comparison, and accessible list', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'A little more connected.' })).toBeVisible();
  await page.getByRole('button', { name: 'Piano, 4 of 5 analyzed entries. Open evidence.' }).click();
  await expect(page.getByRole('complementary', { name: 'Selected topic evidence' })).toContainText('4 entries in this period');
  await page.getByRole('button', { name: /Jan 10, 2025.*Read entry/ }).click();
  await expect(page.getByRole('dialog')).toContainText('I want to learn piano.');
  await expect(page.locator('mark').first()).toHaveText('piano');
  await page.keyboard.press('Escape');
  await page.getByRole('button', { name: 'Compare', exact: true }).click();
  await expect(page.getByRole('region', { name: 'Compare journal periods' })).toBeVisible();
  await expect(page.getByText('3 analyzed entries', { exact: true })).toBeVisible();
  await expect(page.getByText('2 analyzed entries', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'List', exact: true }).first().click();
  await expect(page.getByRole('table')).toContainText('67%');
});

test('review capture before locally saving', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: 'Add entry', exact: true }).click();
  await page.getByRole('button', { name: 'Voice memo', exact: true }).click();
  await page.getByRole('button', { name: /Try a fictional sample transcript/ }).click();
  await expect(page.getByRole('button', { name: 'Save entry', exact: true })).toBeDisabled();
  await page.getByRole('checkbox').check();
  await page.getByRole('button', { name: 'Save entry', exact: true }).click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await expect(page.getByRole('status')).toContainText('Entry saved on this browser');
  await page.reload();
  await page.getByRole('button', { name: 'My journal' }).click();
  await expect(page.getByText('Saved locally · analysis unavailable')).toBeVisible();
});

test('edit invalidates old evidence and mobile has no horizontal overflow', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  await page.getByRole('button', { name: 'My journal' }).click();
  await page.getByRole('button', { name: /Jan 10, 2025/ }).click();
  await page.getByRole('button', { name: 'Edit entry', exact: true }).click();
  await page.getByRole('textbox', { name: 'Approved journal text' }).fill('I practiced guitar.');
  await page.getByRole('button', { name: 'Save entry', exact: true }).click();
  await page.keyboard.press('Escape');
  await page.getByRole('button', { name: 'Neuron map', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Piano, 3 of 4 analyzed entries. Open evidence.' })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test('dashboard screenshot', async ({ page }) => {
  await page.goto('/');
  await page.screenshot({ path: '/tmp/synapse-track-c-desktop.png', fullPage: true });
});

test('clicked neuron details stay open and source entries are clickable', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: 'Piano, 4 of 5 analyzed entries. Open evidence.' }).click();
  const details = page.getByRole('region', { name: 'Piano details', exact: true });
  await page.mouse.move(20, 20);
  await expect(details).toBeVisible();
  await expect(details.getByRole('button', { name: /Jan 10, 2025/ })).toBeVisible();
  await details.getByRole('button', { name: /Jan 10, 2025/ }).click();
  await expect(page.getByRole('dialog')).toContainText('I want to learn piano.');
  await page.keyboard.press('Escape');
  await page.getByRole('button', { name: 'Piano, 4 of 5 analyzed entries. Open evidence.' }).click();
  await page.keyboard.press('Escape');
  await expect(page.getByRole('button', { name: 'Piano, 4 of 5 analyzed entries. Open evidence.' })).toHaveAttribute('aria-expanded', 'false');
});

test('3D brain supports rotation, trackpad pan/pinch, reset and stable filters', async ({ page }) => {
  await page.goto('/');
  const stage = page.getByRole('group', { name: /^Interactive 3D brain map/ });
  const piano = page.getByRole('button', { name: 'Piano, 4 of 5 analyzed entries. Open evidence.' });
  await expect(piano).toBeVisible();
  const before = await piano.boundingBox();
  const bounds = (await stage.boundingBox())!;
  await page.mouse.move(bounds.x+30, bounds.y+60);
  await page.mouse.down();
  await page.mouse.move(bounds.x+125, bounds.y+85, { steps: 8 });
  await page.mouse.up();
  await expect.poll(async () => (await piano.boundingBox())!.x).not.toBe(before!.x);
  await stage.dispatchEvent('wheel', { deltaY: -45, ctrlKey: true, bubbles: true, cancelable: true });
  await expect.poll(async () => Number(await stage.getAttribute('data-camera-zoom'))).toBeGreaterThan(100);
  const zoom = await stage.getAttribute('data-camera-zoom');
  await page.getByRole('combobox', { name: 'Map date range' }).selectOption('2025');
  await expect(stage).toHaveAttribute('data-camera-zoom', zoom!);
  const filtered = page.getByRole('button', { name: 'Piano, 2 of 3 analyzed entries. Open evidence.' });
  const oldPosition = (await filtered.boundingBox())!;
  await stage.dispatchEvent('wheel', { deltaX: 35, deltaY: 20, bubbles: true, cancelable: true });
  await expect.poll(async () => Math.round((await filtered.boundingBox())!.x)).toBe(Math.round(oldPosition.x-35));
  await page.getByRole('button', { name: 'Reset brain view' }).click();
  await expect(stage).toHaveAttribute('data-camera-zoom', '100');
  await stage.focus();
  await page.keyboard.press('+');
  await expect.poll(async () => Number(await stage.getAttribute('data-camera-zoom'))).toBeGreaterThan(100);
  await page.keyboard.press('Home');
  await expect(stage).toHaveAttribute('data-camera-zoom', '100');
});
