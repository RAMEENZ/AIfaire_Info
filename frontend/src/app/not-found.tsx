export default function NotFound() {
  return (
    <div className="flex flex-col items-center justify-center h-screen gap-3 px-6 text-center bg-gray-50">
      <span className="text-5xl font-black text-blue-700">FAIRE</span>
      <p className="text-gray-500 text-sm">Page introuvable</p>
      <a href="/" className="text-sm text-blue-600 hover:underline">
        Retour à l&apos;accueil
      </a>
    </div>
  );
}
