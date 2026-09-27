import {Audio, interpolate, staticFile, useVideoConfig} from 'remotion';
import {PromoSound} from './PromoSound';
import {playbackRate} from './timing';

const frameAt = (baseFrame: number) => Math.round(baseFrame / playbackRate);

export const Promo = () => {
  const {durationInFrames} = useVideoConfig();

  return (
    <>
      <PromoSound />
      <Audio
        src={staticFile('audio/music/digital-clouds.mp3')}
        volume={(frame) => {
          const fade = interpolate(
            frame,
            [0, 15, durationInFrames - 36, durationInFrames - 1],
            [0, 1, 1, 0],
            {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'},
          );
          const reminderDuck = interpolate(
            frame,
            [frameAt(415), frameAt(430), frameAt(470), frameAt(490)],
            [1, 0.4, 0.4, 1],
            {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'},
          );
          return 0.14 * fade * reminderDuck;
        }}
      />
    </>
  );
};
