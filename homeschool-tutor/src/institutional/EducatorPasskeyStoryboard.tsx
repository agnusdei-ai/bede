import { useState } from 'react'
import { Check, ChevronLeft, KeyRound, Laptop, MailCheck, ShieldCheck, Smartphone } from 'lucide-react'
import './EducatorPasskeyStoryboard.css'

type Step = 'invite' | 'choose' | 'verify' | 'done' | 'recover'
const steps: Step[] = ['invite', 'choose', 'verify', 'done']
const descriptions: Record<Step, string> = {
  invite: 'Your school has invited you to Bede.',
  choose: 'Make a passkey using the device you trust.',
  verify: 'Your browser would now open a device verification prompt.',
  done: 'Your educator access is ready for review.',
  recover: 'Recover access with your school and a new passkey.',
}
/** Pure storyboard. No real credential creation, email verification or session issuance. */
export default function EducatorPasskeyStoryboard() {
  const [step, setStep] = useState<Step>('invite')
  const [choice, setChoice] = useState<'device' | 'other'>('device')
  const [attempts, setAttempts] = useState(0)
  const [feedback, setFeedback] = useState('')
  const at = steps.indexOf(step)
  const next = () => { setFeedback(''); setStep(steps[Math.min(at + 1, steps.length - 1)]) }
  return <main className="bede-enroll">
    <div className="bede-enroll__frame">
      <header className="bede-enroll__header"><span className="bede-enroll__mark">✣</span><span>BEDE <small>CLASSICAL EDUCATOR</small></span><span className="bede-enroll__tag">STORYBOARD · FICTIONAL</span></header>
      <div className="bede-enroll__content">
        <p className="bede-enroll__eyebrow">AGNUS DEI TECHNOLOGIES · SCHOOL ACCESS</p>
        <div className="bede-enroll__steps" aria-label="Enrollment progress">{steps.map((s,i)=><span key={s} aria-current={step === s ? 'step' : undefined} className={i <= at && step !== 'recover' ? 'is-current' : ''}>{i + 1}</span>)}</div>
        <h1>{step === 'invite' ? <>Your teaching begins <em>here.</em></> : step === 'choose' ? <>One small step. <em>Secure access.</em></> : step === 'verify' ? <>Verify on <em>your device.</em></> : step === 'done' ? <>All set for <em>the next lesson.</em></> : <>A new key. <em>The same trust.</em></>}</h1>
        <p className="bede-enroll__lede">{descriptions[step]}</p>
        <section className="bede-enroll__panel">
          {step === 'invite' && <><span className="bede-enroll__label">WELCOME TO THE ACADEMY</span><h2>Educator invitation</h2><p>Your school administrator has invited you to join the educator workspace. Confirm your school invitation before creating a passkey.</p><div className="bede-enroll__note"><MailCheck size={20}/> School-affiliated email is used for invitations and recovery coordination, never as a login credential.</div><button onClick={next}>Continue to passkey setup →</button></>}
          {step === 'choose' && <><span className="bede-enroll__label">PASSWORDLESS ACCESS</span><h2>Choose where to keep your passkey</h2><div className="bede-enroll__choices"><button className={choice === 'device' ? 'selected' : ''} onClick={()=>setChoice('device')} aria-pressed={choice === 'device'}><Laptop size={24}/><strong>This device</strong><small>Use an available device authenticator or passkey manager</small></button><button className={choice === 'other' ? 'selected' : ''} onClick={()=>setChoice('other')} aria-pressed={choice === 'other'}><Smartphone size={24}/><strong>Another device or security key</strong><small>Use your phone or compatible FIDO2 key</small></button></div><p>macOS, Windows, Linux and mobile platforms are supported where your browser and authenticator support WebAuthn.</p><button onClick={next}>Continue →</button></>}
          {step === 'verify' && <><span className="bede-enroll__label">DEVICE VERIFICATION</span><h2>Approve your passkey prompt</h2><div className="bede-enroll__note"><KeyRound size={24}/> {choice === 'device' ? 'Your operating system, browser or passkey manager handles biometrics or device PIN.' : 'Your other device or security key performs verification.'}</div><p>Bede never sees your PIN, fingerprint or face. The real browser dialog is intentionally not simulated here.</p><button onClick={()=>{setFeedback('This is only a storyboard. A real credential must be verified by the server before confirmation.');setAttempts(n=>n+1)}}>Simulate browser prompt</button><button className="bede-enroll__textbutton" onClick={()=>{setFeedback('Prompt canceled. You can retry without restarting.');setAttempts(n=>n+1)}}>I canceled · Retry</button><button className="bede-enroll__textbutton" onClick={()=>{setChoice('other');setStep('choose');setFeedback('')}}>Use another device</button>{attempts > 0 && <button className="bede-enroll__textbutton" onClick={next}>Preview confirmation screen →</button>}</>}
          {step === 'done' && <><ShieldCheck className="bede-enroll__success" size={36}/><span className="bede-enroll__label">ILLUSTRATIVE CONFIRMATION</span><h2>Passkey enrollment confirmed</h2><p>This is a fictional success screen. In production, it can appear only after the server verifies and saves a new passkey.</p><div className="bede-enroll__note"><Check size={20}/> Before your first class, add a second independent passkey or security key for backup.</div><button onClick={()=>{setStep('invite');setAttempts(0);setFeedback('')}}>Restart storyboard ↻</button></>}
          {step === 'recover' && <><span className="bede-enroll__label">NO PASSWORD RESET</span><h2>Lost access to your passkey?</h2><p>Contact your school's identity administrator using your verified school email. Your administrator must independently confirm your identity and approve a new passkey ceremony. Email alone never unlocks your account.</p><div className="bede-enroll__note"><ShieldCheck size={20}/> Another already-registered passkey is the fastest supported recovery path.</div><button onClick={()=>{setStep('choose');setFeedback('')}}>Use an existing passkey →</button></>}
          <div className="bede-enroll__feedback" aria-live="polite">{feedback}</div>
        </section>
        <div className="bede-enroll__lower"><button className="bede-enroll__textbutton" onClick={()=>{setStep('recover');setFeedback('')}}>Need help accessing your account?</button>{step !== 'invite' && <button className="bede-enroll__textbutton" onClick={()=>{setStep(step==='recover'?'invite':steps[Math.max(0,at-1)]);setFeedback('')}}><ChevronLeft size={14}/> Back</button>}</div>
      </div>
      <footer>SECURE BY DESIGN <span>DEMONSTRATION ONLY · NO LIVE AUTHENTICATION</span></footer>
    </div>
  </main>
}
