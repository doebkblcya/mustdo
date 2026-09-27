import { Composition } from 'remotion';
import { Promo } from './Promo';
import { baseDurationFrames, playbackRate } from './timing';

export const MyComposition = () => (
  <>
    <Composition id="MustdoPromo" component={Promo} durationInFrames={Math.ceil(baseDurationFrames / playbackRate)} fps={30} width={1080} height={1920} />
  </>
);
