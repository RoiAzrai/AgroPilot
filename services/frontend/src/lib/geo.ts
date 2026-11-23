// Rounds to 4 decimals (about 11 m) and turns -0 into 0.
export function roundCoord(n: number): number {
  const r = Number(n.toFixed(4));
  return r === 0 ? 0 : r;
}

// GeolocationPositionError.code: 1 denied, 2 unavailable, 3 timeout.
export function describeGeoError(code: number): string {
  switch (code) {
    case 1:
      return "Location permission was denied. Enter the coordinates by hand, or allow location in your browser settings.";
    case 3:
      return "Locating took too long. Try again or enter the coordinates by hand.";
    default:
      return "Couldn't work out your location. Enter the coordinates by hand.";
  }
}
