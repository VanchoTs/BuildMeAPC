document.addEventListener('DOMContentLoaded', async () => {
    const AUTH_API = `http://${window.location.hostname}:5075/api/auth`;
    const ADMIN_API = `http://${window.location.hostname}:5075/api/admin`;
    const tbody = document.getElementById('user-list-body');

    // Verify session with backend
    let currentUser: any = null;
    try {
        const response = await fetch(`${AUTH_API}/me`, {
            credentials: 'include'
        });
        if (response.ok) {
            currentUser = await response.json();
        }
    } catch (e) {
        console.error('Session verification failed');
    }

    if (!currentUser || currentUser.role !== 'admin') {
        alert('Access Denied: Admins only.');
        window.location.href = 'index.html';
        return;
    }

    function escapeHtml(text: string) {
        if (!text) return '';
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    loadUsers();

    async function loadUsers() {
        try {
            console.log('Fetching users from:', `${ADMIN_API}/users`);
            const response = await fetch(`${ADMIN_API}/users`, {
                credentials: 'include'
            });

            if (response.ok) {
                const users = await response.json();
                console.log('Users loaded:', users);
                if (users.length === 0) {
                    tbody!.innerHTML = '<tr><td colspan="6" style="text-align: center;">No users found in database.</td></tr>';
                } else {
                    renderUsers(users);
                }
            } else if (response.status === 401 || response.status === 403) {
                alert('Session expired or unauthorized. Logging out.');
                localStorage.removeItem('user');
                window.location.href = 'login.html';
            } else {
                const errorText = await response.text();
                alert(`Failed to load users. Status: ${response.status} ${response.statusText}\n${errorText}`);
            }
        } catch (err) {
            console.error('Connection error:', err);
            alert('Could not connect to the API. Ensure the backend is running at ' + ADMIN_API);
        }
    }

    function renderUsers(users: any[]) {
        if (!tbody) return;
        tbody.innerHTML = '';

        users.forEach(u => {
            const isSelf = u.email === currentUser.email;
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td>${u.id}</td>
                <td>${escapeHtml(u.fullName)}</td>
                <td>${escapeHtml(u.email)} ${isSelf ? '<small>(You)</small>' : ''}</td>
                <td><span class="role-badge role-${u.role}">${u.role}</span></td>
                <td>${new Date(u.createdAt).toLocaleDateString()}</td>
                <td>
                    <select class="role-select" data-id="${u.id}" style="width: auto; padding: 0.25rem;" ${isSelf ? 'disabled' : ''}>
                        <option value="user" ${u.role === 'user' ? 'selected' : ''}>User</option>
                        <option value="writer" ${u.role === 'writer' ? 'selected' : ''}>Writer</option>
                        <option value="admin" ${u.role === 'admin' ? 'selected' : ''}>Admin</option>
                    </select>
                    ${!isSelf ? `<button class="btn btn-outline delete-btn" data-id="${u.id}" style="padding: 0.25rem 0.5rem; color: var(--danger-color); margin-left: 0.5rem;">Delete</button>` : ''}
                </td>
            `;

            if (!isSelf) {
                const select = tr.querySelector('.role-select') as HTMLSelectElement;
                select.addEventListener('change', async () => {
                    await updateRole(u.id, select.value);
                });

                const deleteBtn = tr.querySelector('.delete-btn') as HTMLButtonElement;
                deleteBtn.addEventListener('click', async () => {
                    if (confirm(`Are you sure you want to delete user ${escapeHtml(u.fullName)}?`)) {
                        await deleteUser(u.id);
                    }
                });
            }

            tbody.appendChild(tr);
        });
    }

    async function deleteUser(userId: number) {
        try {
            const response = await fetch(`${ADMIN_API}/users/${userId}`, {
                method: 'DELETE',
                credentials: 'include'
            });

            if (response.ok) {
                alert('User deleted successfully.');
                loadUsers();
            } else {
                const err = await response.text();
                alert(`Failed to delete user: ${err}`);
            }
        } catch (err) {
            console.error('Error deleting user:', err);
        }
    }

    async function updateRole(userId: number, newRole: string) {
        try {
            const response = await fetch(`${ADMIN_API}/users/${userId}/role`, {
                method: 'PATCH',
                headers: {
                    'Content-Type': 'application/json'
                },
                credentials: 'include',
                body: JSON.stringify(newRole)
            });

            if (response.ok) {
                alert('Role updated successfully.');
                loadUsers();
            } else {
                alert('Failed to update role.');
            }
        } catch (err) {
            console.error('Error updating role:', err);
        }
    }
});
