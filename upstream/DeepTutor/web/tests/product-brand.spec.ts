import { createInstance } from "i18next";
import { describe, expect, it } from "vitest";
import { brandAppCatalog, PRODUCT_NAME } from "../lib/product-brand";
import en from "../locales/en/app.json";
import zh from "../locales/zh/app.json";
import de from "../locales/de/app.json";
import fr from "../locales/fr/app.json";
import pl from "../locales/pl/app.json";
import uk from "../locales/uk/app.json";
import { CO_WRITER_SAMPLE_TEMPLATE } from "../app/(workspace)/co-writer/sampleTemplate";

describe("application brand boundaries", () => {
  it("brands ordinary product copy in every shipped language without renaming translation keys", () => {
    for (const catalog of [en, zh, de, fr, pl, uk]) {
      const adapted = brandAppCatalog(catalog);
      expect(Object.keys(adapted)).toEqual(Object.keys(catalog));
      expect(adapted["Uploaded to DeepTutor"]).toContain(PRODUCT_NAME);
      expect(adapted["Welcome to DeepTutor"]).toContain(PRODUCT_NAME);
      expect(adapted["Only stable, published DeepTutor releases are considered."])
        .toEqual(catalog["Only stable, published DeepTutor releases are considered."]);
    }
  });

  it("leaves user values intact because branding precedes translation interpolation", async () => {
    const i18n = createInstance();
    await i18n.init({
      lng: "en", resources: { en: { translation: brandAppCatalog(en) } },
      keySeparator: false, interpolation: { escapeValue: false },
    });
    const key = "Stored at memory/backup/{{name}}. v2 starts fresh — interact with DeepTutor and click Update on each doc to build memory.";
    const result = i18n.t(key, { name: "DeepTutor_Introduction.pdf" });
    expect(result).toContain("memory/backup/DeepTutor_Introduction.pdf");
    expect(result).toContain("interact with DeepSteam");
    expect(i18n.t("{{name}} Exploring…", { name: "DeepTutor personal agent" }))
      .toContain("DeepTutor personal agent");
  });

  it("preserves upstream URLs, technical tokens, unlisted content and the source catalog", () => {
    const source = {
      "settings.agentSetup.prompt": "Configure DeepTutor. https://github.com/HKUDS/DeepTutor DeepTutorApp deeptutor DeepTutor/1 DeepTutor_Notes.md docs.DeepTutor.info DEEPTUTOR_HOME",
      "student quotation": "I use DeepTutor.",
      "e.g. HKUDS/DeepTutor": "e.g. HKUDS/DeepTutor",
    };
    const adapted = brandAppCatalog(source);
    expect(adapted["settings.agentSetup.prompt"])
      .toBe("Configure DeepSteam. https://github.com/HKUDS/DeepTutor DeepTutorApp deeptutor DeepTutor/1 DeepTutor_Notes.md docs.DeepTutor.info DEEPTUTOR_HOME");
    expect(adapted["student quotation"]).toBe("I use DeepTutor.");
    expect(adapted["e.g. HKUDS/DeepTutor"]).toBe("e.g. HKUDS/DeepTutor");
    expect(source["settings.agentSetup.prompt"]).toMatch(/^Configure DeepTutor\./);
  });

  it("brands new writing examples without a serializer that rewrites saved drafts", () => {
    expect(CO_WRITER_SAMPLE_TEMPLATE).toContain("# DeepSteam Co-Writer");
    expect(CO_WRITER_SAMPLE_TEMPLATE).toContain('"app_name": "DeepSteam"');
    expect(CO_WRITER_SAMPLE_TEMPLATE).not.toContain("DeepTutor");
    expect(brandAppCatalog(en)["settings.agentSetup.prompt"])
      .toContain("https://github.com/HKUDS/DeepTutor");
  });
});
