import AppKit
import CoreImage
import CoreImage.CIFilterBuiltins

public enum QRCode {
    /// A square QR code for `url`, drawn without smoothing so the squares stay sharp.
    public static func image(for url: URL, size: CGFloat) -> NSImage? {
        let filter = CIFilter.qrCodeGenerator()
        filter.message = Data(url.absoluteString.utf8)
        filter.correctionLevel = "M"
        guard let output = filter.outputImage, size > 0 else { return nil }
        let extent = output.extent
        let scale = size / extent.width
        let scaled = output.samplingNearest().transformed(by: CGAffineTransform(scaleX: scale, y: scale))
        let rep = NSCIImageRep(ciImage: scaled)
        let image = NSImage(size: NSSize(width: size, height: size))
        image.addRepresentation(rep)
        return image
    }
}
