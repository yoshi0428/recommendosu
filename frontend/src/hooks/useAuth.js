import {useEffect, useState} from 'react'
import {
    getCurrentUser,
    login,
    logout,
} from '../api/client'

export function useAuth() {
    const [user, setUser] = useState(null)
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState(null)

    useEffect(() => {
        checkAuthentication()
    }, [])

    async function checkAuthentication() {
        try {
            const data = await getCurrentUser()
            console.log('Authenticated user:', data)
            setUser(data)
        } catch (err) {
            setError('Failed to connect to the backend.')
        } finally {
            setLoading(false)
        }
    }

    async function handleLogout() {
        try {
            await logout()
            setUser(null)
        } catch (err) {
            setError(err.message)
        }
    }

    return {
        user,
        loading,
        error,
        login,
        logout: handleLogout,
    }
}