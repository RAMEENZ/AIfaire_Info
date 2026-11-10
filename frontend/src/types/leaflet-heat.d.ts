// `leaflet.heat` ne publie pas de types et ne s'importe pas comme un module :
// il se greffe sur l'objet global L au chargement (L.heatLayer). Cette
// déclaration suffit à autoriser l'import d'effet de bord ; l'usage passe
// ensuite par un cast, comme avant, faute d'API typée en amont.
//
// Depuis la v1.0.0, le point d'entrée par défaut ("leaflet.heat") est un
// module ES qui exporte la classe `HeatLayer` et ne patch plus L par effet
// de bord. Le sous-chemin dist/leaflet-heat-global.js est le build qui
// restaure ce comportement (voir CHANGELOG v1.0.0) — c'est celui-ci qu'on
// importe désormais pour garder L.heatLayer sans réécrire l'appelant.
declare module "leaflet.heat";
declare module "leaflet.heat/dist/leaflet-heat-global.js";
