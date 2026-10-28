import ToastMessage from "./ToastMessage";
import { useState } from "react";

export type CategoryImage = { file_token?: string; local_media_id?: string; name: string; path: string };

export default function CategoryImageEditor({ images, onChange, tr, onBusy, uploadUrl = "/api/admin/category-images", imageKind = "category" }: {
  uploadUrl?: string;
  imageKind?: "category" | "shipping";
  images: CategoryImage[];
  onChange: (images: CategoryImage[]) => void;
  tr: (zh: string, en: string) => string;
  onBusy: (busy: boolean) => void;
}) {
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");
  async function add(files: FileList | null) {
    if (!files?.length) return;
    setError("");
    if (images.length + files.length > 12) {
      setError(tr("最多可添加 12 张图片。", "Add up to 12 images."));
      return;
    }
    const uploaded: CategoryImage[] = [];
    setUploading(true); onBusy(true);
    try {
      for (const file of Array.from(files)) {
        if (file.size > 6 * 1024 * 1024) throw Error(tr("单张图片不能超过 6 MB。", "Each image must be 6 MB or smaller."));
        const response = await fetch(uploadUrl, {
          method: "POST", body: file,
          headers: { "Content-Type": "application/octet-stream", "X-File-Name": encodeURIComponent(file.name) },
        });
        const data = await response.json();
        if (!response.ok) throw Error(data.detail || tr("图片上传失败。", "Image upload failed."));
        uploaded.push(data);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : tr("图片上传失败。", "Image upload failed."));
    } finally {
      if (uploaded.length) onChange([...images, ...uploaded]);
      setUploading(false); onBusy(false);
    }
  }
  return <fieldset className="category-images" disabled={uploading}>
    <legend>{imageKind === "shipping" ? tr("发货图片（选填）", "Shipping images (optional)") : tr("品类图片（选填）", "Category images (optional)")}</legend>
    <p>{tr("最多 12 张，每张不超过 6 MB，支持 PNG、JPEG、WebP。移除后可重新添加图片。", "Up to 12 PNG, JPEG or WebP images, 6 MB each. Remove an image to replace it.")}</p>
    <div className="category-image-list">{images.map((image, index) => <figure key={image.local_media_id || image.file_token || index}>
      {image.path ? <img src={image.path} alt={image.name}/> : <span>{image.name}</span>}
      <figcaption title={image.name}>{image.name}</figcaption>
      <button type="button" onClick={() => onChange(images.filter((_, i) => i !== index))} aria-label={tr(`移除 ${image.name}`, `Remove ${image.name}`)}>{tr("移除", "Remove")}</button>
    </figure>)}</div>
    <label className="category-image-upload">{uploading ? tr("正在上传…", "Uploading…") : imageKind === "shipping" ? tr("添加发货图片", "Add shipping images") : tr("添加品类图片", "Add category images")}
      <input type="file" accept="image/png,image/jpeg,image/webp" multiple disabled={uploading || images.length >= 12}
        onChange={e => { const files = e.currentTarget.files; void add(files); e.currentTarget.value = ""; }}/>
    </label>
    {images.length > 0 && <button type="button" className="category-image-clear" onClick={() => onChange([])}>{tr("移除全部图片", "Remove all images")}</button>}
    {error && <ToastMessage role="alert">{error}</ToastMessage>}
  </fieldset>;
}
