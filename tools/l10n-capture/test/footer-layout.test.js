import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import sharp from 'sharp';
import {
  LAYOUT_PORTRAIT,
  LAYOUT_LANDSCAPE,
  AMOUNT_TEXT_RE,
  layoutFromContentCenters,
  layoutFromAmountHits,
  layoutFromBottomPixelStrip,
  fuseLayoutSignals,
  refinePortraitLayoutAfterContinue,
} from '../lib/footer-layout.js';

const CFG = {
  viewport: { width: 1920, height: 911 },
  footerLayout: {
    portraitMaxSpan: 0.35,
    landscapeMinSpan: 0.62,
    portraitCenterMin: 0.22,
    portraitCenterMax: 0.78,
    contentMinBrightness: 40,
    yStart: 0.62,
  },
};

describe('footer-layout', () => {
  it('layoutFromContentCenters：中央窄條為直版', () => {
    const r = layoutFromContentCenters([0.42, 0.48, 0.55], CFG);
    assert.equal(r.layout, LAYOUT_PORTRAIT);
    assert.ok(r.span <= 0.35);
  });

  it('layoutFromContentCenters：全寬為橫版', () => {
    const r = layoutFromContentCenters([0.08, 0.5, 0.92], CFG);
    assert.equal(r.layout, LAYOUT_LANDSCAPE);
  });

  it('layoutFromContentCenters：樣本不足為 inconclusive', () => {
    assert.equal(layoutFromContentCenters([0.5], CFG).layout, null);
  });

  it('AMOUNT_TEXT_RE 認金額不認語系標籤', () => {
    assert.ok(AMOUNT_TEXT_RE.test('P 3,335,556.60'));
    assert.ok(AMOUNT_TEXT_RE.test('12.50'));
    assert.ok(!AMOUNT_TEXT_RE.test('Balance'));
  });

  it('layoutFromAmountHits：金額中心窄帶為直版', () => {
    const r = layoutFromAmountHits([
      { xNorm: 0.45, text: 'P 1,234.00' },
      { xNorm: 0.52, text: '3.00' },
    ], CFG);
    assert.equal(r.layout, LAYOUT_PORTRAIT);
    assert.equal(r.source, 'amount');
  });

  it('fuse：footer 直版覆寫 carousel 橫版（letterbox）', () => {
    const r = fuseLayoutSignals({
      carouselPortrait: false,
      footerLayout: LAYOUT_PORTRAIT,
    });
    assert.equal(r.portraitLayout, true);
    assert.match(r.reason, /overrides-carousel/);
  });

  it('fuse：carousel 直版 + footer 滿寬橫版 → 忽略 footer（亮邊 letterbox）', () => {
    const r = fuseLayoutSignals({
      carouselPortrait: true,
      footerLayout: LAYOUT_LANDSCAPE,
      footerSpan: 1.0,
      cfg: CFG,
    });
    assert.equal(r.portraitLayout, true);
    assert.match(r.reason, /full-bleed-ignored/);
  });

  it('fuse：carousel 直版 + footer 合理橫版 span → 可覆寫', () => {
    const r = fuseLayoutSignals({
      carouselPortrait: true,
      footerLayout: LAYOUT_LANDSCAPE,
      footerSpan: 0.75,
      cfg: CFG,
    });
    assert.equal(r.portraitLayout, false);
    assert.match(r.reason, /footer-landscape-overrides/);
  });

  it('fuse：carousel 直版 + footer 橫版但無 span → 不覆寫', () => {
    const r = fuseLayoutSignals({
      carouselPortrait: true,
      footerLayout: LAYOUT_LANDSCAPE,
      cfg: CFG,
    });
    assert.equal(r.portraitLayout, true);
    assert.match(r.reason, /span-unknown/);
  });

  it('fuse：footer 無結論時沿用 carousel', () => {
    assert.equal(
      fuseLayoutSignals({ carouselPortrait: true, footerLayout: null }).portraitLayout,
      true,
    );
    assert.equal(
      fuseLayoutSignals({ carouselPortrait: false, footerLayout: null }).portraitLayout,
      false,
    );
  });

  it('layoutFromBottomPixelStrip：中央亮帶判直版', async () => {
    const { width: W, height: H } = CFG.viewport;
    // 全黑 + 底部中央亮條（模擬 letterbox 直版 footer）
    const png = await sharp({
      create: {
        width: W,
        height: H,
        channels: 3,
        background: { r: 8, g: 8, b: 8 },
      },
    })
      .composite([{
        input: await sharp({
          create: {
            width: 400,
            height: 120,
            channels: 3,
            background: { r: 180, g: 180, b: 200 },
          },
        }).png().toBuffer(),
        left: 760,
        top: 780,
      }])
      .png()
      .toBuffer();

    const r = await layoutFromBottomPixelStrip(png, CFG);
    assert.equal(r.layout, LAYOUT_PORTRAIT);
    assert.equal(r.source, 'pixel');
  });

  it('layoutFromBottomPixelStrip：底部全寬亮帶判橫版', async () => {
    const { width: W, height: H } = CFG.viewport;
    const png = await sharp({
      create: {
        width: W,
        height: H,
        channels: 3,
        background: { r: 8, g: 8, b: 8 },
      },
    })
      .composite([{
        input: await sharp({
          create: {
            width: 1700,
            height: 100,
            channels: 3,
            background: { r: 160, g: 160, b: 170 },
          },
        }).png().toBuffer(),
        left: 100,
        top: 800,
      }])
      .png()
      .toBuffer();

    const r = await layoutFromBottomPixelStrip(png, CFG);
    assert.equal(r.layout, LAYOUT_LANDSCAPE);
  });

  it('refinePortraitLayoutAfterContinue：可關閉', async () => {
    const r = await refinePortraitLayoutAfterContinue(
      {},
      { ...CFG, footerLayout: { ...CFG.footerLayout, enabled: false } },
      true,
    );
    assert.equal(r.portraitLayout, true);
    assert.equal(r.footer.skipped, true);
  });
});
