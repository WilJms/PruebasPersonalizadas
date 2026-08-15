import AxeBuilder from "@axe-core/playwright";
import { expect, test, type BrowserContext, type Page } from "@playwright/test";

async function assertNoCriticalAccessibilityViolations(page: Page) {
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  expect(
    results.violations.filter((item) =>
      item.impact === "critical" || item.impact === "serious",
    ),
  ).toEqual([]);
}

async function assertViewportDoesNotOverflow(page: Page, width: number) {
  await page.setViewportSize({ width, height: 780 });
  await expect.poll(
    () => page.evaluate(() => document.documentElement.scrollWidth),
  ).toBeLessThanOrEqual(width);
}

test("critical Stage 1 journey survives browser restart and enforces evidence-first", async ({
  browser,
}) => {
  let context: BrowserContext = await browser.newContext({
    viewport: { width: 1280, height: 900 },
  });
  let page = await context.newPage();
  const title = `Actividad sintética ${Date.now()}`;

  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Entrar al workspace", exact: true })).toBeVisible();
  await page.getByLabel("Correo institucional").fill("teacher@example.test");
  await page.getByRole("button", { name: "Continuar" }).click();
  await expect(page.getByRole("heading", { name: "Actividades", exact: true })).toBeVisible();
  await assertNoCriticalAccessibilityViolations(page);

  await page.locator("main").getByRole("link", { name: "Nueva actividad", exact: true }).click();
  await page.getByLabel("Título").fill(title);
  await page.getByLabel("Número de preguntas").fill("1");
  await page.locator('input[name="target_total_minutes"]').fill("3");
  await page.getByRole("checkbox", { name: /Respuesta abierta breve/ }).uncheck();
  await page.getByRole("checkbox", { name: /Bullets estructurados/ }).uncheck();
  await page.getByRole("checkbox", { name: /Selección entre alternativas/ }).check();
  await expect(page.getByRole("radio", { name: "No requerida" })).toBeChecked();
  await page.locator('input[name="assignment_prompt"]').setInputFiles({
    name: "assignment.md",
    mimeType: "text/markdown",
    buffer: Buffer.from(
      "# Consigna\n\nExplique cómo una decisión produce una consecuencia local y señale un límite observable.\n",
    ),
  });
  await page.locator('input[name="rubric"]').setInputFiles({
    name: "rubric.md",
    mimeType: "text/markdown",
    buffer: Buffer.from(
      "# Rúbrica\n\nSe valora una explicación causal respaldada por evidencia localizada.\n",
    ),
  });
  await page.getByRole("button", { name: "Crear, cargar y estimar" }).click();
  await expect(page.getByRole("heading", { name: "Blueprint listo para iniciar", exact: true })).toBeVisible();
  await expect(page.getByText(/límite superior USD/)).toBeVisible();
  await page.getByRole("button", { name: "Confirmar e iniciar blueprint" }).click();

  await expect(
    page.getByRole("heading", { name: "Catálogo de comprensión revisable", exact: true }),
  ).toBeVisible();
  await expect(page.getByText(/Dificultad derivada/).first()).toBeVisible();
  await expect(page.getByText("Preflight determinista")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Catálogo factible" })).toBeVisible();
  await expect(page.getByText("Revisión P05")).toHaveCount(0);
  await page.getByRole("button", { name: "Editar blueprint" }).click();
  await page.getByRole("textbox", { name: "Nombre de dimensión 1" }).fill(
    "Comprensión verificable revisada por preflight",
  );
  await page.getByRole("button", { name: "Guardar nueva versión" }).click();
  await expect(
    page.getByRole("heading", {
      name: "Comprensión verificable revisada por preflight",
      exact: true,
    }),
  ).toBeVisible();
  await expect(page.getByText("Blueprint · versión 2")).toBeVisible();
  await assertViewportDoesNotOverflow(page, 320);
  await assertViewportDoesNotOverflow(page, 390);
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.getByRole("button", { name: "Aprobar blueprint" }).click();
  await expect(page.getByRole("button", { name: "Abrir lote de entregas" })).toBeVisible();
  await page.getByRole("button", { name: "Abrir lote de entregas" }).click();
  await expect(page.getByRole("heading", { name: "Lote de entregas" })).toBeVisible();
  await page.getByRole("link", { name: "Alta individual" }).click();

  await page.getByLabel("Referencia seudónima").fill("synthetic_subject_001");
  await page.locator('input[name="submission_file"]').setInputFiles({
    name: "submission.md",
    mimeType: "text/markdown",
    buffer: Buffer.from(
      "# Entrega\n\nLa deduplicación ocurre antes del promedio para evitar doble peso.\n\nLos extremos se conservan y se marcan porque la evidencia no permite afirmar que sean errores.\n",
    ),
  });
  await page.getByRole("button", { name: "Cargar y estimar" }).click();
  await expect(page.getByRole("button", { name: "Confirmar e iniciar pipeline" })).toBeVisible();
  await page.getByRole("button", { name: "Confirmar e iniciar pipeline" }).click();
  await expect(page.getByRole("button", { name: "Revisar evaluación" })).toBeVisible();

  const storedSession = await context.storageState();
  await context.close();
  context = await browser.newContext({
    storageState: storedSession,
    viewport: { width: 1280, height: 900 },
  });
  page = await context.newPage();
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Actividades", exact: true })).toBeVisible();
  const recoveredCard = page
    .getByRole("heading", { name: title, exact: true })
    .locator("xpath=ancestor::article");
  await expect(recoveredCard).toContainText("NEEDS_REVIEW");
  await recoveredCard.getByRole("button", { name: "Revisar Assessment" }).click();

  await expect(page.getByRole("heading", { name: "Revisión basada en evidencia", exact: true })).toBeVisible();
  await expect(page.getByText("Contenido del estudiante")).toBeVisible();
  await expect(page.getByText("Información del evaluador")).toBeVisible();
  await expect(page.getByText(/Mejor respuesta/).first()).toBeVisible();
  await expect(page.getByText(/Posible error conceptual/).first()).toBeVisible();
  await expect(page.getByText(/Dificultad derivada/).first()).toBeVisible();
  const approve = page.getByRole("button", { name: "Aprobar Assessment" });
  await expect(approve).toBeDisabled();

  const popupPromise = page.waitForEvent("popup");
  await page.getByRole("button", { name: "Cargar y verificar fuente exacta" }).click();
  const source = await popupPromise;
  await expect(source.locator("body")).toContainText("La deduplicación ocurre antes del promedio");
  await source.close();
  await expect(page.getByText("Fuente cargada y localizador verificado")).toBeVisible();
  await expect(approve).toBeEnabled();

  const evaluationTab = page.getByRole("tab", { name: /Evaluación/ });
  await evaluationTab.focus();
  await page.keyboard.press("End");
  const guideTab = page.getByRole("tab", { name: /Guía estructurada/ });
  await expect(guideTab).toBeFocused();
  await expect(page.getByText("Elementos observables", { exact: true })).toBeVisible();
  await expect(page.getByText("Posibles errores conceptuales a observar", { exact: true })).toBeVisible();
  await expect(page.getByText("No permite inferir", { exact: true })).toBeVisible();
  await assertNoCriticalAccessibilityViolations(page);

  await assertViewportDoesNotOverflow(page, 320);
  await assertViewportDoesNotOverflow(page, 390);
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.getByRole("tab", { name: /Evaluación/ }).click();
  await approve.click();
  await expect(page.getByText("Assessment aprobado")).toBeVisible();
  await page.getByRole("button", { name: "Evaluación PDF" }).click();
  await expect(page.getByRole("link", { name: "Descargar Evaluación PDF" })).toBeVisible();

  await page.reload();
  await expect(page.getByText("Assessment aprobado")).toBeVisible();
  await expect(page.getByRole("button", { name: "Guía PDF" })).toBeVisible();
  await context.close();
});
