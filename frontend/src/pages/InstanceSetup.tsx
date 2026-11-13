/**
 * @fileoverview 无实例时显示的首次设置向导。
 */

import { useEffect, useLayoutEffect, useRef, useState, type FormEvent, type ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowLeft, ArrowRight, Check, ClipboardCheck, FileUp, Globe, Languages, MonitorSmartphone } from 'lucide-react'
import type { AnimationItem } from 'lottie-web'
import { api } from '../api/client'
import type { Parameters } from '../api/generated'
import { useApp, useConnection } from '../app/context'
import { INSTANCE_NAME_PATTERN } from '../app/instanceName'
import { motionReducedActive } from '../app/motionPrefs'
import { Select } from '../components/FormControls'
import { ProjectLogo } from '../components/ProjectLogo'
import { useIsDesktop } from '../app/useIsDesktop'
import { ErrorBox } from '../components/ui'
import { languages, type Language } from '../i18n'

const STEPS = [
  {title: 'WelcomeSelectLanguage', hint: 'WelcomeHint', artwork: 'language'},
  {title: 'ImportTitle', hint: 'ImportHint', artwork: 'import'},
  {title: 'ServerTitle', hint: 'ServerHint', artwork: 'region'},
  {title: 'EmulatorTitle', hint: 'EmulatorHint', artwork: 'emulator'},
  {title: 'ReviewTitle', hint: 'ReviewHint', artwork: 'review'},
] as const

const FALLBACK_ICONS: Record<typeof STEPS[number]['artwork'], typeof Languages> = {
  language: Languages,
  import: FileUp,
  region: Globe,
  emulator: MonitorSmartphone,
  review: ClipboardCheck,
}
const DEFAULT_PACKAGES: Record<Language, string> = {
  'zh-CN': 'com.bilibili.azurlane',
  'en-US': 'com.YoStarEN.AzurLane',
  'ja-JP': 'com.YoStarJP.AzurLane',
  'zh-TW': 'com.hkmanjuu.azurlane.gp',
}
const SERIAL_PRESETS = [
  ['auto', 'Auto'],
  ['127.0.0.1:5555', 'BlueStacks / 雷电'],
  ['127.0.0.1:62001', 'Nox / 夜神'],
  ['127.0.0.1:59865', 'Nox 64-bit'],
  ['127.0.0.1:7555', 'MuMu X'],
  ['127.0.0.1:16384', 'MuMu 12 / MuMu Pro'],
  ['127.0.0.1:21503', 'MEmu / 逍遥'],
  ['emulator-5554', 'Android Emulator'],
  ['wsa-0', 'Windows Subsystem for Android'],
] as const

function serverRegion(packageName: string) {
  if (packageName === DEFAULT_PACKAGES['en-US']) return 'en'
  if (packageName === DEFAULT_PACKAGES['ja-JP']) return 'jp'
  if (packageName.startsWith(DEFAULT_PACKAGES['zh-TW'])) return 'tw'
  return 'cn'
}

/** 向导插图：优先加载 Lottie 动画，加载失败或资源缺失时退回静态图标。 */
function WindowsSetupArtwork({name, play, fallback}: {name: string; play: boolean; fallback: ReactNode}) {
  const container = useRef<HTMLDivElement>(null)
  const [animation, setAnimation] = useState<AnimationItem>()
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    let active = true
    let item: AnimationItem | undefined
    function showFallback() {
      if (active) setFailed(true)
    }
    void import('lottie-web/build/player/lottie_light.js').then(({default: lottie}) => {
      if (!active || !container.current) return
      item = lottie.loadAnimation({
        container: container.current, renderer: 'svg', autoplay: false, loop: false,
        path: `${import.meta.env.BASE_URL}setup-illustrations/${name}.json`,
      })
      item.addEventListener('DOMLoaded', () => { if (active) setAnimation(item) })
      item.addEventListener('data_failed', showFallback)
    }).catch(showFallback)
    return () => {
      active = false
      item?.destroy()
    }
  }, [name])

  useEffect(() => {
    if (!animation || !play) return
    // Windows 的图示使用 0–120 帧作为进入段，后面的帧留给离场。
    const stopIfReduced = () => {
      if (motionReducedActive()) animation.goToAndStop(119, true)
    }
    if (motionReducedActive()) stopIfReduced()
    else animation.playSegments([0, 120], true)
    const media = window.matchMedia('(prefers-reduced-motion: reduce)')
    media.addEventListener('change', stopIfReduced)
    return () => { media.removeEventListener('change', stopIfReduced) }
  }, [animation, play])

  return failed ? fallback : <div className="setup-illustration-art" ref={container}/>
}

/**
 * 首次设置向导（OOBE）：五步走完语言、导入、服务器、模拟器与确认，最后创建实例并跳到总览页。
 * 桌面宽度下播放入场缩放动画；用户开始交互或动画播完即结束。
 */
export function InstanceSetup() {
  const {language, setLanguage, schema, refresh, t, ui, notify} = useApp()
  const connection = useConnection()
  const navigate = useNavigate()
  const desktop = useIsDesktop()
  const panel = useRef<HTMLElement>(null)
  // 入场动画未结束时为 true；动画播完或用户聚焦卡片都会关掉它。
  const [entering, setEntering] = useState(true)
  const [step, setStep] = useState(1)
  const [name, setName] = useState('ap')
  const [packageName, setPackageName] = useState(DEFAULT_PACKAGES[language])
  const [serverName, setServerName] = useState('')
  const [serial, setSerial] = useState('127.0.0.1:5555')
  const [file, setFile] = useState<File>()
  const [createdName, setCreatedName] = useState<string>()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useLayoutEffect(() => {
    const card = panel.current
    const screen = card?.parentElement
    if (!card || !screen || motionReducedActive() || !window.matchMedia('(min-width: 951px)').matches) {
      setEntering(false)
      return
    }
    // 把屏幕与卡片的尺寸比写进 CSS 变量，setup-window-enter 动画据此把卡片从全屏缩到位。
    card.style.setProperty('--setup-entry-scale-x', String(screen.clientWidth / card.offsetWidth))
    card.style.setProperty('--setup-entry-scale-y', String(screen.clientHeight / card.offsetHeight))
    function finish(event: AnimationEvent) {
      if (event.target === card && event.animationName === 'setup-window-enter') setEntering(false)
    }
    card.addEventListener('animationend', finish)
    card.addEventListener('animationcancel', finish)
    return () => {
      card.removeEventListener('animationend', finish)
      card.removeEventListener('animationcancel', finish)
    }
  }, [])

  const label = (key: string) => t(`Gui.OOBE.${key}`)
  const fields = schema?.args.Alas?.Emulator
  const packageOptions = [...new Set([...Object.values(DEFAULT_PACKAGES), ...(fields?.PackageName?.option ?? [])])]
    .filter((item): item is string => typeof item === 'string' && item !== 'auto')
  const region = serverRegion(packageName)
  const prefixes = region === 'cn' ? ['cn_android', 'cn_ios', 'cn_channel'] : [region]
  const serverOptions = (fields?.ServerName?.option ?? []).filter((item): item is string =>
    typeof item === 'string' && prefixes.some(prefix => item.startsWith(`${prefix}-`)))
  const selectedServer = serverOptions.includes(serverName) ? serverName : serverOptions[0] ?? 'disabled'
  const packageLabels = (schema?.translations.Emulator as {PackageName?: Record<string, string>} | undefined)?.PackageName
  const canSave = connection === 'ready' && !busy
  const locked = busy || Boolean(createdName)

  function changeStep(next: number) {
    setError('')
    setStep(next)
    window.scrollTo(0, 0)
  }

  function choosePackage(next: string) {
    setPackageName(next)
    setServerName('')
  }

  function packageLabel(value: string) {
    const packageRegion = serverRegion(value)
    const official = Object.values(DEFAULT_PACKAGES).includes(value)
    const localized = official ? label(`Server${packageRegion.toUpperCase()}`) : packageLabels?.[value]
    return localized && !localized.includes(value) ? `${localized} (${value})` : localized || value
  }

  async function finish(buildParams: () => Parameters['instances.create'] | Promise<Parameters['instances.create']>) {
    if (!canSave) return
    setBusy(true)
    setError('')
    try {
      // 实例已经写入时，重试只读取列表，避免创建同名实例。
      const created = createdName ?? (await api.request('instances.create', await buildParams())).instance
      setCreatedName(created)
      await refresh()
      notify(ui('instance.created'))
      navigate(`/i/${encodeURIComponent(created)}/overview`, {replace: true})
    } catch (cause) {
      setError((cause as Error).message)
    } finally {
      setBusy(false)
    }
  }

  function importConfig(targetFile = file) {
    if (!targetFile || !canSave) return
    void finish(async () => {
      const uploaded = await api.request('instances.importConfig', {
        name: targetFile.name.replace(/\.json$/i, ''),
        content: await targetFile.text(),
      })
      return {name: 'ap', import_file: uploaded.name}
    })
  }

  function onFileChange(event: React.ChangeEvent<HTMLInputElement>) {
    const picked = event.currentTarget.files?.[0]
    if (!picked) return
    setFile(picked)
    setError('')
    importConfig(picked)
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (step !== STEPS.length) return
    void finish(() => ({name, emulator: {
      serial: serial.trim() || 'auto', package_name: packageName, server_name: selectedServer,
    }}))
  }

  const current = STEPS[step - 1]
  const artwork = current.artwork
  const choosingLanguage = current.title === 'WelcomeSelectLanguage'
  const importing = current.title === 'ImportTitle'
  const packageField = <label>
    {t('Emulator.PackageName.name')}
    <Select value={packageName} onChange={event => choosePackage(event.target.value)}>
      {packageOptions.map(value => <option key={value} value={value}>{packageLabel(value)}</option>)}
    </Select>
  </label>

  const FallbackIcon = FALLBACK_ICONS[artwork] ?? Globe

  return <section
    ref={panel}
    className={`panel instance-setup-card setup-wizard${choosingLanguage ? ' setup-language-step' : ''}`}
    data-entering={entering || undefined}
    aria-labelledby="instance-setup-title"
    onFocusCapture={() => setEntering(false)}
  >
    {!choosingLanguage && <header className="setup-brand">
      <ProjectLogo size={52}/>
      <div>
        <p className="setup-brand-title">{label('WelcomeTitle')}</p>
        <p className="muted">{label('WelcomeDescription')}</p>
      </div>
    </header>}
    <ol className="setup-steps" aria-label={label('WelcomeDescription')}>
      {STEPS.map((item, index) => <li key={item.title} aria-current={index === step - 1 ? 'step' : undefined} data-done={index < step - 1 || undefined}>
        <span className="setup-step-number" aria-hidden="true">{index < step - 1 ? <Check size={14}/> : index + 1}</span>
        <span>{label(item.title)}</span>
      </li>)}
    </ol>
    {desktop && <div className="setup-illustration" aria-hidden="true">
      <WindowsSetupArtwork
        key={artwork}
        name={artwork}
        play={!entering}
        fallback={<div className="setup-illustration-mark"><FallbackIcon size={104} strokeWidth={1.35}/></div>}
      />
    </div>}
    <form className="setup-form" onSubmit={submit}>
      <div className="setup-step-content form-stack" key={step}>
        <header>
          <h1 id="instance-setup-title">{label(current.title)}</h1>
          <p className="muted">{label(current.hint)}</p>
        </header>
        {importing && <div className="setup-import">
          <FileUp size={22} aria-hidden="true"/>
          <div>
            <strong>{label('ImportCardTitle')}</strong>
            <p className="muted">{label('ImportCardText')}</p>
            <label className="button secondary file-button">
              {ui('instance.importPick')}
              <input type="file" accept=".json,application/json" disabled={locked} onChange={onFileChange}/>
            </label>
            {file && <p className="setup-file-name" role="status">{file.name}</p>}
          </div>
        </div>}
        {choosingLanguage && <div className="setup-languages" role="group" aria-labelledby="instance-setup-title">
          {Object.entries(languages).map(([value, title]) => <button type="button" className="button secondary" aria-pressed={language === value} key={value} onClick={() => {
            const next = value as Language
            setLanguage(next)
            if (language !== next) choosePackage(DEFAULT_PACKAGES[next])
          }}>{title}</button>)}
        </div>}
        {step === 3 && <>
          {packageField}
          <label>{t('Emulator.ServerName.name')}
            <Select value={selectedServer} onChange={event => setServerName(event.target.value)}>
              {(serverOptions.length ? serverOptions : ['disabled']).map(value =>
                <option key={value} value={value}>{t(`Emulator.ServerName.${value}`)}</option>)}
            </Select>
          </label>
        </>}
        {step === 4 && <>
          <label>{label('EmulatorSerial')}
            <input list="setup-serial-presets" value={serial} maxLength={256} onChange={event => setSerial(event.target.value)} />
            <datalist id="setup-serial-presets">
              {SERIAL_PRESETS.map(([value, title]) => <option key={value} value={value}>{title}</option>)}
            </datalist>
          </label>
          {packageField}
        </>}
        {step === 5 && <dl className="setup-review">
          <div><dt><label htmlFor="setup-instance-name">{label('ReviewConfigName')}</label></dt><dd>
            <input id="setup-instance-name" required pattern={INSTANCE_NAME_PATTERN} maxLength={64} value={createdName ?? name} readOnly={locked} onChange={event => setName(event.target.value)}/>
          </dd></div>
          <div><dt>{label('ReviewLanguage')}</dt><dd>{languages[language]}</dd></div>
          <div><dt>{label('ReviewServer')}</dt><dd>{label(`Server${region.toUpperCase()}`)}</dd></div>
          <div><dt>{t('Emulator.ServerName.name')}</dt><dd>{t(`Emulator.ServerName.${selectedServer}`)}</dd></div>
          <div><dt>{label('ReviewSerial')}</dt><dd>{serial.trim() || 'auto'}</dd></div>
          <div><dt>{label('ReviewPackage')}</dt><dd>{packageName}</dd></div>
        </dl>}
        {connection !== 'ready' && <p className="muted" role="status">{ui('connection.connecting')}</p>}
        {error && <ErrorBox message={error}/>}
      </div>
      <footer className="setup-footer">
        {step > 1 && <button type="button" className="button secondary" disabled={locked} onClick={() => changeStep(step - 1)}>
          <ArrowLeft size={16}/>{label('ButtonBack')}
        </button>}
        <div className="setup-actions">
          {importing && file && <button type="button" className="button primary" disabled={!canSave} onClick={() => importConfig()}>
            {busy ? ui('instance.creating') : createdName ? ui('common.retry') : label('ImportButton')}
          </button>}
          {step < STEPS.length && <button type="button" className={`button ${importing && file ? 'secondary' : 'primary'}`} disabled={locked} onClick={() => changeStep(step + 1)}>
            {label(importing && file ? 'ImportSkip' : 'ButtonNext')}<ArrowRight size={16}/>
          </button>}
          {step === STEPS.length && <button type="submit" className="button primary" disabled={!canSave}>
            {busy ? ui('instance.creating') : createdName ? ui('common.retry') : label('ButtonCreate')}<Check size={16}/>
          </button>}
        </div>
      </footer>
    </form>
  </section>
}
