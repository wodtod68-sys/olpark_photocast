// 올림픽공원 지도. 다른 지도로 바꿀 때는 이 파일만 고친다.
// 스팟 좌표(Spot.map)는 이 이미지의 픽셀 좌표(MAP_SIZE)를 쓴다.
// 원본: pics/olparkmap.png (같은 해상도의 WebP로 변환)
import mapSrc from './olparkmap.webp';

export const MAP_SIZE = { width: 2464, height: 1728 };

export function ParkMap({ className }: { className?: string }) {
  return (
    <img
      className={className}
      src={mapSrc}
      width={MAP_SIZE.width}
      height={MAP_SIZE.height}
      alt="올림픽공원 안내 지도"
    />
  );
}
