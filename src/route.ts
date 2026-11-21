// 예상 이미지 화면 주소: #/spot/<id>/<YYYY-MM-DD>/<시>
export const resultHash = (spotId: string, date: string, hour: number) => `#/spot/${spotId}/${date}/${hour}`;
