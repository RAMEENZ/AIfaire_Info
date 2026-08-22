/**
 * Mise en phrase du rythme de collecte annoncé par `/api/health`.
 *
 * Les heures viennent du serveur et non d'une constante locale : INGEST_HOURS
 * est configurable, et une copie côté client divergerait à la première
 * modification sans que rien ne le signale — exactement le défaut qui a fait
 * survivre « 870+ flux » dans le README pendant que le code en servait 848.
 */
export function libelleRythme(
  heures: number[] | undefined,
  fuseau: string | undefined,
  alertesHoraires: boolean | undefined
): string {
  if (!heures || heures.length === 0) return "";
  const liste = [...heures].sort((a, b) => a - b).map((h) => `${h}h`);
  // « 7h, 12h et 19h » plutôt que « 7h, 12h, 19h » : c'est une phrase lue par
  // un humain dans une infobulle, pas une énumération technique.
  const enumere =
    liste.length > 1 ? `${liste.slice(0, -1).join(", ")} et ${liste[liste.length - 1]}` : liste[0];
  const ville = fuseau ? ` (${fuseau.split("/").pop()?.replace(/_/g, " ")})` : "";
  const base = `Collecte complète à ${enumere}${ville}`;
  return alertesHoraires
    ? `${base}. Météo, crues et séismes sont relevés toutes les heures, nuit comprise.`
    : `${base}.`;
}
