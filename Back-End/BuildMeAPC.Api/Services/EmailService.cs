using System.Net;
using System.Net.Mail;

namespace BuildMeAPC.Api.Services
{
    public interface IEmailService
    {
        // For automated system emails (uses appsettings.json)
        Task SendSystemEmailAsync(string to, string subject, string body);
        
        // For admin responses (uses provided password per request)
        Task SendEmailAsync(string senderEmail, string senderPassword, string to, string subject, string body);
    }

    public class EmailService : IEmailService
    {
        private readonly IConfiguration _config;

        public EmailService(IConfiguration config)
        {
            _config = config;
        }

        public async Task SendSystemEmailAsync(string to, string subject, string body)
        {
            var senderEmail = _config["SmtpSettings:SenderEmail"] ?? "";
            var senderPassword = _config["SmtpSettings:Password"] ?? "";
            await SendEmailAsync(senderEmail, senderPassword, to, subject, body);
        }

        public async Task SendEmailAsync(string senderEmail, string senderPassword, string to, string subject, string body)
        {
            var server = _config["SmtpSettings:Server"] ?? "smtp.gmail.com";
            var port = int.Parse(_config["SmtpSettings:Port"] ?? "587");
            var senderName = _config["SmtpSettings:SenderName"] ?? "BuildMeAPC";

            if (string.IsNullOrEmpty(senderEmail) || string.IsNullOrEmpty(senderPassword))
            {
                throw new ArgumentException("Sender email and password are required.");
            }

            try 
            {
                using var client = new SmtpClient(server, port)
                {
                    Credentials = new NetworkCredential(senderEmail, senderPassword),
                    EnableSsl = true
                };

                var mailMessage = new MailMessage
                {
                    From = new MailAddress(senderEmail, senderName),
                    Subject = subject,
                    Body = body,
                    IsBodyHtml = true
                };
                mailMessage.To.Add(to);

                await client.SendMailAsync(mailMessage);
            }
            catch (Exception ex)
            {
                Console.WriteLine($"Email send failed: {ex.Message}");
                throw; 
            }
        }
    }
}
