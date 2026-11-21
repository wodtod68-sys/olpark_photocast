import type { Spot } from '../data/types';
import { Masthead } from './Masthead';
import { MapView } from './MapView';
import { SpotIndex } from './SpotIndex';

export function MapScreen({ spots }: { spots: Spot[] }) {
  return (
    <>
      <Masthead />
      <main>
        <MapView spots={spots} />
        <SpotIndex spots={spots} />
      </main>
    </>
  );
}
