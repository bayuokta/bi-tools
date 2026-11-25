// Jembatan sementara antara modul view dan helper UI di app.js.
// app.js mengisi properti ini sebelum init(); view hanya memanggil saat runtime.
// Tujuannya memecah file besar tanpa memindahkan seluruh helper sekaligus.

function missing(name) {
  return function () {
    throw new Error("Helper UI belum terpasang: " + name);
  };
}

export const app = {
  addLog: missing("addLog"),
  api: missing("api"),
  apiReady: missing("apiReady"),
  applyMetaSteps: missing("applyMetaSteps"),
  loadOutputs: missing("loadOutputs"),
  openFolderPicker: missing("openFolderPicker"),
  parentDir: missing("parentDir"),
  reportError: missing("reportError"),
  setChip: missing("setChip"),
  setMetaStep: missing("setMetaStep"),
  showView: missing("showView"),
  startJob: missing("startJob"),
  toast: missing("toast")
};
