import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import {
  PORTRAIT_ACTIVE_REGION_MAX_WIDTH,
  fractionsToRegion,
  isPortraitActiveRegion,
  inferPortraitLayout,
  loadingCropLayoutKey,
  promoTextBandFromCarousel,
  resolveLoadingPromoRegion,
  formatPromoRegion,
} from '../lib/loading-promo-region.js';

const VP = { width: 1920, height: 911 };
const CFG = {
  viewport: VP,
  loading: {
    portraitActiveRegionMaxWidth: 600,
    portraitCenterMaxOffsetRatio: 0.12,
    promoTextFractionsPortrait: { left: 0.30, top: 0.62, width: 0.40, height: 0.16 },
    promoTextFractionsLandscape: { left: 0.08, top: 0.50, width: 0.84, height: 0.28 },
    compareRegionCenter: { left: 640, top: 200, width: 640, height: 500 },
    compareRegion: { left: 1000, top: 60, width: 900, height: 420 },
  },
};

describe('loading-promo-region', () => {
  it('fractionsToRegion 換算 viewport 比例', () => {
    const r = fractionsToRegion({ left: 0.1, top: 0.2, width: 0.5, height: 0.3 }, VP);
    assert.equal(r.left, 192);
    assert.equal(r.top, 182);
    assert.equal(r.width, 960);
    assert.equal(r.height, 273);
  });

  it('isPortraitActiveRegion：置中窄區為直版', () => {
    const region = { left: 660, top: 150, width: 500, height: 400 };
    assert.equal(isPortraitActiveRegion(region, CFG), true);
  });

  it('isPortraitActiveRegion：右側窄輪播仍為橫版', () => {
    const region = { left: 1042, top: 159, width: 500, height: 416 };
    assert.equal(isPortraitActiveRegion(region, CFG), false);
  });

  it('isPortraitActiveRegion：寬區非直版', () => {
    const region = { left: 100, top: 60, width: 900, height: 400 };
    assert.equal(region.width >= PORTRAIT_ACTIVE_REGION_MAX_WIDTH, true);
    assert.equal(isPortraitActiveRegion(region, CFG), false);
  });

  it('inferPortraitLayout 優先 capture-meta', () => {
    assert.equal(inferPortraitLayout({ portraitLayout: false }, CFG), false);
    assert.equal(inferPortraitLayout({ portraitLayout: true }, CFG), true);
  });

  it('loadingCropLayoutKey', () => {
    assert.equal(loadingCropLayoutKey(true), 'portrait');
    assert.equal(loadingCropLayoutKey(false), 'landscape');
    assert.equal(loadingCropLayoutKey(null), 'landscape');
  });

  it('promoTextBandFromCarousel 略過窄輪播區', () => {
    const narrow = { left: 660, top: 150, width: 500, height: 400 };
    assert.equal(promoTextBandFromCarousel(narrow, CFG), null);
    const wide = { left: 1000, top: 60, width: 900, height: 420 };
    const band = promoTextBandFromCarousel(wide, CFG);
    assert.ok(band);
    assert.equal(band.width, 900);
  });

  it('resolveLoadingPromoRegion 橫版用底部寬帶', () => {
    const carousel = { left: 1000, top: 60, width: 900, height: 420 };
    const { layoutKey, portraitLayout, region } = resolveLoadingPromoRegion(
      { portraitLayout: false, loadingPromoRegion: carousel },
      CFG,
    );
    assert.equal(layoutKey, 'landscape');
    assert.equal(portraitLayout, false);
    assert.ok(region.width > 600);
  });

  it('formatPromoRegion', () => {
    assert.equal(formatPromoRegion({ left: 10, top: 20, width: 100, height: 50 }), '[10,20 100x50]');
    assert.equal(formatPromoRegion(null), '');
  });
});
