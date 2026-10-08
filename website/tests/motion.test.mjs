import test from 'node:test';
import assert from 'node:assert/strict';
import { createContentMotion, nextTabIndex } from '../src/scripts/motion.mjs';

function fixture() {
  let change;
  const preference = { matches:false, addEventListener:(_, fn) => { change = fn; } };
  const animations = [];
  const element = { animate(frames) {
    const animation = { frames, canceled:false, cancel() { this.canceled=true;this.oncancel?.(); } };
    animations.push(animation); return animation;
  } };
  return { preference, element, animations, change:() => change() };
}
test('rapid tab switches cancel stale motion and keep the latest direction', () => {
  const f=fixture(), animate=createContentMotion(f.preference);
  animate([f.element],1); animate([f.element],-1);
  assert.equal(f.animations[0].canceled,true);
  assert.equal(f.animations[1].canceled,false);
  assert.equal(f.animations[1].frames[0].transform,'translateX(-12px)');
});
test('reduced motion cancels running transitions and suppresses future ones', () => {
  const f=fixture(), animate=createContentMotion(f.preference);
  animate([f.element]); f.preference.matches=true; f.change();
  assert.equal(f.animations[0].canceled,true);
  animate([f.element]); assert.equal(f.animations.length,1);
  f.preference.matches=false; animate([f.element]); assert.equal(f.animations.length,2);
});
test('finished transitions and unavailable animation APIs do not block content changes', () => {
  const f=fixture(), animate=createContentMotion(f.preference);
  animate([null,{},f.element]); f.animations[0].onfinish();
  animate([f.element]); assert.equal(f.animations[0].canceled,false);
});
test('tab keyboard navigation wraps at boundaries and ignores unrelated keys', () => {
  assert.equal(nextTabIndex('ArrowLeft',0,5),4);
  assert.equal(nextTabIndex('ArrowRight',4,5),0);
  assert.equal(nextTabIndex('Home',3,5),0);
  assert.equal(nextTabIndex('End',0,5),4);
  assert.equal(nextTabIndex('Tab',2,5),null);
});
