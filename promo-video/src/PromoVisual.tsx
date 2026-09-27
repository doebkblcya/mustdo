import {
  AbsoluteFill,
  Easing,
  Img,
  interpolate,
  staticFile,
  useCurrentFrame,
} from 'remotion';
import {playbackRate} from './timing';

// One physical capsule carries the voice input, transcript, task and reminder.
const paper = '#f9f9f9';
const ink = '#111211';
const muted = '#737674';
const font = '"PingFang SC", "Noto Sans CJK SC", sans-serif';
const ease = Easing.bezier(0.22, 1, 0.36, 1);
const motionFrames = {state: 45, title: 30, detail: 18};
const pageSwitchFrames = 20;
const headlineStyle = {fontSize: 120, fontWeight: 520, letterSpacing: -5, lineHeight: 1.28};
const cardTitleSize = 54;
const cardMetaSize = 30;
const firstTransition = {
  voice: 103,
  titleOut: 73,
  expand: 109,
  reveal: 117,
  transcript: 123,
  eyebrow: 83,
};
const taskPage = {labelOut: 200, titleIn: 210, morph: 210, firstCard: 215, secondCard: 225};
const reminderPage = {start: 319, titleIn: 329, morph: 405, detailIn: 430};
const ending = {sceneOut: 493, logo: 500};
const progress = (frame: number, from: number, to: number) =>
  interpolate(frame, [from, to], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: ease,
  });
const smoothProgress = (frame: number, from: number, to: number) =>
  interpolate(frame, [from, to], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: Easing.inOut(Easing.cubic),
  });
const mix = (a: number, b: number, p: number) => a + (b - a) * p;

const MiniIcon = ({name, size = 38}: {name: 'mic' | 'notifications_active'; size?: number}) => (
  <Img src={staticFile(`icons/${name}.svg`)} style={{width: size, height: size}} />
);

const TaskContent = ({
  title,
  meta,
}: {
  title: string;
  meta: string;
}) => (
  <div style={{display: 'flex', alignItems: 'center', width: '100%', height: '100%', padding: '0 54px', gap: 34}}>
    <div style={{width: 42, height: 42, border: '2px solid #a6aaa7', borderRadius: '50%', flex: '0 0 auto'}} />
    <div style={{flex: 1, minWidth: 0}}>
      <div style={{fontSize: cardTitleSize, fontWeight: 480, letterSpacing: -1.5, lineHeight: 1.25, whiteSpace: 'nowrap'}}>{title}</div>
      <div style={{fontSize: cardMetaSize, color: muted, marginTop: 9}}>{meta}</div>
    </div>
  </div>
);

const VoiceWave = ({frame}: {frame: number}) => (
  <div style={{display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8, height: 62}}>
    {Array.from({length: 9}, (_, index) => (
      <div
        key={index}
        style={{
          width: 5,
          height: 12 + 34 * Math.abs(Math.sin(frame * 0.17 + index * 0.75)) * (0.72 + 0.28 * Math.sin(frame * 0.047 + 0.5) ** 2),
          borderRadius: 8,
          background: '#fff',
          opacity: 0.9,
        }}
      />
    ))}
  </div>
);

export const PromoVisual = () => {
  const frame = useCurrentFrame() * playbackRate;
  const voiceToText = progress(frame, firstTransition.voice, firstTransition.voice + motionFrames.state);
  const panelExpand = progress(frame, firstTransition.expand, firstTransition.expand + motionFrames.state);
  const textToCard = progress(frame, taskPage.morph, taskPage.morph + motionFrames.state);
  const reminderFocus = progress(frame, reminderPage.start, reminderPage.start + motionFrames.state);
  const whiteReveal = progress(frame, firstTransition.reveal, firstTransition.reveal + motionFrames.title);
  const transcriptOpacity = progress(frame, firstTransition.transcript, firstTransition.transcript + motionFrames.detail);
  const meetingOpacity = progress(frame, taskPage.firstCard, taskPage.firstCard + motionFrames.detail);
  const secondaryCardIn = progress(frame, taskPage.secondCard, taskPage.secondCard + motionFrames.state);
  const thirdCardIn = progress(frame, taskPage.secondCard + 10, taskPage.secondCard + 10 + motionFrames.state);
  const stackOpacity = secondaryCardIn * (1 - progress(frame, reminderPage.start, reminderPage.start + motionFrames.title));
  const reminderMorph = smoothProgress(frame, reminderPage.morph, reminderPage.morph + motionFrames.state);
  const taskDetailsOut = smoothProgress(frame, reminderPage.morph + 7, reminderPage.morph + 29);
  const notificationIn = smoothProgress(frame, reminderPage.detailIn, reminderPage.detailIn + motionFrames.title);
  const outro = progress(frame, ending.logo, ending.logo + motionFrames.state);
  const sceneOut = 1 - progress(frame, ending.sceneOut, ending.sceneOut + motionFrames.title);

  const carrierLeft = mix(mix(mix(132, 84, voiceToText), 128, reminderFocus), 120, reminderMorph);
  const carrierTop = mix(mix(1244, 673, voiceToText), 845, textToCard);
  const carrierFocusedTop = mix(mix(carrierTop, 815, reminderFocus), 965, reminderMorph);
  const carrierWidth = mix(mix(mix(816, 912, voiceToText), 824, reminderFocus), 840, reminderMorph);
  const taskCardHeight = mix(mix(146, 386, panelExpand), 187, textToCard);
  const carrierHeight = mix(taskCardHeight, 266, reminderMorph);
  const sharedTitleLeft = mix(130, 55, reminderMorph);
  const sharedTitleTop = mix((taskCardHeight - 112) / 2, 99, reminderMorph);
  const bellFrames = frame - (reminderPage.detailIn + 14);
  const bellWiggle = bellFrames > 0 && bellFrames < 22 ? 8 * Math.exp(-bellFrames / 9) * Math.sin(bellFrames * 0.85) : 0;
  const logoSettle = interpolate(outro, [0, 0.78, 0.9, 1], [1, 1.028, 0.994, 1]);

  return (
    <AbsoluteFill style={{background: paper, color: ink, fontFamily: font, overflow: 'hidden'}}>
      <div style={{
        position: 'absolute', left: mix(77, 540, outro), top: mix(91, 875, outro),
        fontSize: mix(52, 150, outro), fontWeight: 720, lineHeight: 1,
        letterSpacing: mix(-3.2, -8, outro), translate: `${-50 * outro}% 0`, scale: logoSettle, zIndex: 10,
      }}>mustdo</div>

      <div style={{
        position: 'absolute', left: 86, top: 411, width: 920, ...headlineStyle,
        opacity: progress(frame, 6, 6 + motionFrames.title) * (1 - progress(frame, firstTransition.titleOut, firstTransition.titleOut + pageSwitchFrames)),
        translate: `0 ${mix(44, 0, progress(frame, 6, 6 + motionFrames.title)) - 54 * progress(frame, firstTransition.titleOut, firstTransition.titleOut + pageSwitchFrames)}px`,
      }}>
        想到什么，<br /><span style={{paddingLeft: 120}}>直接说。</span>
      </div>

      <div style={{
        position: 'absolute', left: 86, top: 375, width: 890,
        fontSize: 48, color: muted,
        opacity: progress(frame, firstTransition.eyebrow, firstTransition.eyebrow + pageSwitchFrames) * (1 - progress(frame, taskPage.labelOut, taskPage.labelOut + pageSwitchFrames)),
      }}>你刚刚说</div>
      <div style={{
        position: 'absolute', left: 86, top: 363, width: 920, ...headlineStyle,
        opacity: progress(frame, taskPage.titleIn, taskPage.titleIn + pageSwitchFrames) * (1 - progress(frame, reminderPage.start, reminderPage.start + pageSwitchFrames)),
      }}>一句话，<br /><span style={{paddingLeft: 120}}>三件事。</span></div>
      <div style={{
        position: 'absolute', left: 86, top: 331, width: 920, ...headlineStyle,
        opacity: progress(frame, reminderPage.titleIn, reminderPage.titleIn + pageSwitchFrames) * sceneOut,
      }}>重要的事，<br /><span style={{paddingLeft: 120}}>到点提醒。</span></div>

      {/* One card carries the voice, transcript, task and reminder states. */}
      <div style={{
        position: 'absolute', left: carrierLeft, top: carrierFocusedTop,
        width: carrierWidth, height: carrierHeight,
        borderRadius: mix(mix(mix(82, 45, panelExpand), 94, textToCard), 42, reminderMorph),
        backgroundColor: frame >= firstTransition.reveal + motionFrames.title ? '#ffffff' : '#090909',
        border: `1px solid rgba(25, 28, 26, ${0.06 * voiceToText})`,
        boxShadow: `0 ${mix(21, 38, textToCard)}px ${mix(58, 80, textToCard)}px rgba(21,24,22,${mix(mix(0.09, 0.13, textToCard), 0.09, reminderMorph)})`,
        rotate: `${mix(mix(-2.1 * textToCard, -1, reminderFocus), 0, reminderMorph)}deg`,
        transform: `perspective(1500px) rotateY(${mix(-5 * textToCard, 0, reminderFocus)}deg) rotateX(${mix(3 * textToCard, 0, reminderFocus)}deg)`,
        zIndex: 4,
        opacity: sceneOut,
        overflow: 'hidden',
      }}>
        <div style={{
          position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 46,
          color: '#fff', fontSize: 43, fontWeight: 680,
        }}>
          <div style={{filter: 'invert(1)'}}><MiniIcon name="mic" size={41} /></div>
          <span>按住说话</span>
          <VoiceWave frame={frame} />
        </div>
        <div style={{
          position: 'absolute', inset: 0, background: '#fff',
          clipPath: `inset(0 ${100 * (1 - whiteReveal)}% 0 0)`,
        }}>
          <div style={{position: 'absolute', inset: 0, padding: '44px 55px', opacity: transcriptOpacity}}>
            <div style={{fontSize: 27, color: muted, marginBottom: 19}}>语音识别</div>
            <div style={{fontSize: 51, fontWeight: 430, letterSpacing: -1.5, lineHeight: 1.55}}>
              {['明天下午三点开会，', '周五买牛奶，', '给妈妈回电话。'].map((line, index) => {
                const lineIn = progress(frame, firstTransition.transcript + index * 8, firstTransition.transcript + index * 8 + motionFrames.detail);
                const lineOut = progress(frame, taskPage.firstCard + index * 10, taskPage.firstCard + index * 10 + motionFrames.detail);
                return <div key={line} style={{opacity: lineIn * (1 - lineOut), translate: `0 ${mix(18, 0, lineIn) - 13 * lineOut}px`}}>{line}</div>;
              })}
            </div>
          </div>
          <div style={{
            position: 'absolute', inset: 0, background: '#fff',
            clipPath: `inset(0 ${100 * (1 - meetingOpacity)}% 0 0)`,
          }}>
            <div style={{
              position: 'absolute', left: 54, top: (taskCardHeight - 42) / 2,
              width: 42, height: 42, border: '2px solid #a6aaa7', borderRadius: '50%',
              opacity: 1 - taskDetailsOut, scale: mix(1, 0.7, taskDetailsOut),
            }} />
            <div style={{
              position: 'absolute', left: sharedTitleLeft, top: sharedTitleTop,
              fontSize: cardTitleSize, fontWeight: 480, letterSpacing: -1.5,
              lineHeight: 1.25, whiteSpace: 'nowrap',
            }}>下午三点开会</div>
            <div style={{
              position: 'absolute', left: sharedTitleLeft, top: sharedTitleTop + 76.5,
              fontSize: cardMetaSize, color: muted, opacity: 1 - taskDetailsOut,
            }}>明天 15:00</div>
            <div style={{
              position: 'absolute', left: carrierWidth - 92, top: (taskCardHeight - 38) / 2,
              opacity: 0.68 * (1 - taskDetailsOut),
            }}><MiniIcon name="notifications_active" size={38} /></div>
            <div style={{
              position: 'absolute', left: 55, top: 43, fontSize: 27, color: muted,
              display: 'flex', alignItems: 'center', gap: 16, opacity: notificationIn,
            }}>
              <span style={{display: 'inline-flex', rotate: `${bellWiggle}deg`}}><MiniIcon name="notifications_active" size={28} /></span> 微信提醒
            </div>
            <div style={{
              position: 'absolute', left: 55, top: 176,
              fontSize: cardMetaSize, color: muted, opacity: notificationIn,
            }}>明天 14:30 · 提前 30 分钟</div>
          </div>
        </div>
      </div>

      <div style={{
        position: 'absolute', left: mix(292, 163, secondaryCardIn) - 510 * reminderFocus,
        top: mix(905, 1108, secondaryCardIn) + 115 * reminderFocus,
        width: 799, height: 177, borderRadius: 90, background: '#fff',
        boxShadow: `0 ${mix(18, 32, secondaryCardIn)}px ${mix(48, 77, secondaryCardIn)}px rgba(21,24,22,${mix(0.06, 0.1, secondaryCardIn)})`,
        opacity: stackOpacity,
        rotate: `${mix(5, 0, secondaryCardIn)}deg`,
        transform: `perspective(1500px) rotateY(${mix(7, 1, secondaryCardIn)}deg) rotateX(${mix(5, 0, secondaryCardIn)}deg)`,
        scale: mix(0.94, 1, secondaryCardIn), zIndex: 3,
      }}><TaskContent title="周五买牛奶" meta="周五" /></div>

      <div style={{
        position: 'absolute', left: mix(-9, 96, thirdCardIn) + 650 * reminderFocus,
        top: mix(1120, 1344, thirdCardIn) + 170 * reminderFocus,
        width: 820, height: 177, borderRadius: 90, background: '#fff',
        boxShadow: `0 ${mix(18, 32, thirdCardIn)}px ${mix(48, 77, thirdCardIn)}px rgba(21,24,22,${mix(0.06, 0.09, thirdCardIn)})`,
        opacity: thirdCardIn * (1 - progress(frame, reminderPage.start, reminderPage.start + motionFrames.title)),
        rotate: `${mix(-5, 0, thirdCardIn)}deg`,
        transform: `perspective(1500px) rotateY(${mix(-7, -1, thirdCardIn)}deg) rotateX(${mix(5, 0, thirdCardIn)}deg)`,
        scale: mix(0.94, 1, thirdCardIn), zIndex: 2,
      }}><TaskContent title="给妈妈回电话" meta="今天" /></div>

    </AbsoluteFill>
  );
};
