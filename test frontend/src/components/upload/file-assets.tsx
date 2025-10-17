import { cn } from "../../lib/utils";
import excelIcon from "../../assets/excel_icon.png";
import otherIcon from "../../assets/other_icon.png";
import pdfIcon from "../../assets/pdf_icon.png";
import wordIcon from "../../assets/word_icon.png";

export function iconForExtension(ext?: string | null) {
  if (!ext) return otherIcon;
  const value = ext.toLowerCase();
  if (value === "pdf") return pdfIcon;
  if (value === "doc" || value === "docx") return wordIcon;
  if (value === "xls" || value === "xlsx") return excelIcon;
  return otherIcon;
}

export function UploadIllustration({ className }: { className?: string }) {
  return (
    <div className={cn("flex items-center justify-center gap-6", className)}>
      <img src={wordIcon} alt="" className="h-20 w-20]" />
      <img src={pdfIcon} alt="" className="h-24 w-24]" />
      <img src={excelIcon} alt="" className="h-20 w-20]" />
    </div>
  );
}
