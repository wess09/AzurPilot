
interface ElectronApi {
  readonly versions: Readonly<NodeJS.ProcessVersions>
  readonly windowControls: {
    readonly tray: () => void
    readonly minimize: () => void
    readonly maximize: () => void
    readonly close: () => void
  }
}

declare interface Window {
  electron: Readonly<ElectronApi>
}
