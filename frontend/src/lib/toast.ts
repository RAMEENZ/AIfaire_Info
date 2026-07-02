// Mini système de toast (pub/sub, zéro dépendance). Le composant <Toaster />
// s'abonne et affiche ; n'importe quel code appelle toast("…").
export type ToastKind = "success" | "error" | "info";

export interface ToastItem {
  id: number;
  message: string;
  kind: ToastKind;
}

type Listener = (t: ToastItem) => void;

let listeners: Listener[] = [];
let nextId = 1;

export function toast(message: string, kind: ToastKind = "info"): void {
  const item: ToastItem = { id: nextId++, message, kind };
  listeners.forEach((l) => l(item));
}

export function subscribeToToasts(fn: Listener): () => void {
  listeners.push(fn);
  return () => {
    listeners = listeners.filter((l) => l !== fn);
  };
}
