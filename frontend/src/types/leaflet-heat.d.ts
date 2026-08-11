// `leaflet.heat` ne publie pas de types et ne s'importe pas comme un module :
// il se greffe sur l'objet global L au chargement (L.heatLayer). Cette
// déclaration suffit à autoriser l'import d'effet de bord ; l'usage passe
// ensuite par un cast, comme avant, faute d'API typée en amont.
declare module "leaflet.heat";
