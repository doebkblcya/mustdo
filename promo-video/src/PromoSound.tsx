import {Audio, Sequence, staticFile} from 'remotion';
import {PromoVisual} from './PromoVisual';
import {playbackRate} from './timing';

const frameAt = (baseFrame: number) => Math.round(baseFrame / playbackRate);

const Cue = ({from, file, volume}: {from: number; file: string; volume: number}) => (
  <Sequence from={frameAt(from)}>
    <Audio src={staticFile(`audio/sfx/${file}`)} volume={volume} />
  </Sequence>
);

export const PromoSound = () => (
  <>
    <PromoVisual />
    <Cue from={103} file="soft-switch-tap.wav" volume={0.56} />
    <Cue from={200} file="air-sweep.wav" volume={0.37} />
    <Cue from={430} file="gentle-bell.wav" volume={0.32} />
  </>
);
